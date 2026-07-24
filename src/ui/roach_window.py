"""A standalone cockroach sprite that scuttles in from the screen edge and
chases Modi.

It is its own transparent top-level window (independent of the pet window) so it
can move on its own path. Flow:

    spawn  -> appear at the far screen edge, run toward Modi
    close  -> emit ROACH_SIGHTED once (the pet reacts: freeze, lift jhola, flee)
    chase  -> keep ~ROACH_SEE_DISTANCE behind Modi while he panics
    calm   -> when Modi stops panicking, scuttle off-screen and hide

The window reads Modi's live position/state straight off the PetWindow it is
handed; all state changes are driven by the shared EventBus.
"""
import json
import os

from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QRect
from PyQt6.QtGui import QPixmap, QPainter, QTransform, QGuiApplication
from PyQt6.QtWidgets import QWidget

from src.config import Config
from src.constants import (
    FRAME_INTERVAL_MS, PetState,
    ROACH_SPEED, ROACH_SPAWN_GAP, ROACH_SEE_DISTANCE, ROACH_EXIT_SPEED,
)
from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger("RoachWindow")

ROACH_DIR = os.path.join("assets", "sprites", "cockroach")
ROACH_META = os.path.join(ROACH_DIR, "roach_swarm.json")

# States in which Modi can be startled by the roach (he must be able to see it —
# not already fleeing, being dragged, or airborne/busy).
_VULNERABLE = {
    PetState.IDLE, PetState.WALK, PetState.SIT, PetState.SLEEP, PetState.WAVE,
}
# While Modi is in one of these he is mid-panic; the roach keeps chasing.
_PANIC_STATES = {PetState.SLING, PetState.PANIC_RUN}

# Keep this band behind Modi: close in past the far edge, back off if he doubles
# back into us, so a visible gap always survives (matches the reference art).
_STANDOFF = ROACH_SEE_DISTANCE
_HYST = 70.0
# Safety: never let a roach linger forever if Modi somehow never panics.
_MAX_LIFETIME_SEC = 30.0


class RoachWindow(QWidget):
    def __init__(self, event_bus: EventBus, pet_window):
        super().__init__()
        self.event_bus = event_bus
        self.pet = pet_window

        self._frames: list[QPixmap] = []
        self._mirrored: list[QPixmap] = []
        self._frame_index = 0
        self._fps = 14
        self._base_scale = 0.4
        self._load_frames()

        self.roach_w = self._frames[0].width() if self._frames else 120
        self.roach_h = self._frames[0].height() if self._frames else 40

        # Logical horizontal centre of the roach; -1 direction faces left.
        self._center_x = 0.0
        self._direction = -1
        self._active = False
        self._sighted = False
        self._modi_panicked = False
        self._exiting = False
        self._life = 0.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFixedSize(self.roach_w, self.roach_h)

        self.event_bus.subscribe(EventType.ROACH_SPAWN_REQUESTED, self._on_event, executor="gui")
        self.event_bus.subscribe(EventType.SPRITE_CHANGED, self._on_event, executor="gui")

        self._move_timer = QTimer(self)
        self._move_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._move_timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._advance_frame)

    # ------------------------------------------------------------------ assets
    def _load_frames(self):
        try:
            with open(ROACH_META, encoding="utf-8") as f:
                meta = json.load(f)
            self._base_scale = float(meta.get("base_scale", 0.4))
            sheet = QPixmap(os.path.join(ROACH_DIR, meta["sprite_sheet"]))
            anim = meta["animations"]["roach_run"]
            self._fps = int(anim.get("suggested_fps", 14))
            for fr in anim["frames"]:
                sub = sheet.copy(fr["x"], fr["y"], fr["w"], fr["h"])
                sw = max(1, int(fr["w"] * self._base_scale))
                sh = max(1, int(fr["h"] * self._base_scale))
                scaled = sub.scaled(sw, sh, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
                self._frames.append(scaled)
            flip = QTransform().scale(-1, 1)
            self._mirrored = [p.transformed(flip) for p in self._frames]
            logger.info(f"Loaded {len(self._frames)} roach frames ({self.width()}x{self.height()}).")
        except Exception as e:  # a broken roach pack must never crash the pet
            logger.error(f"Could not load roach sprite: {e}")

    # ------------------------------------------------------------------- screen
    def _screen(self) -> QRect:
        scr = self.pet.screen() or QGuiApplication.primaryScreen()
        if scr is None:
            from src.physics.collision import CollisionResolver
            return CollisionResolver.get_virtual_desktop_geometry()
        return scr.availableGeometry()

    def _modi_center(self) -> float:
        return self.pet.physics.x + self.pet.pet_width / 2

    # -------------------------------------------------------------------- spawn
    def _on_event(self, event_type: str, data: dict):
        if event_type == EventType.ROACH_SPAWN_REQUESTED:
            self.spawn()
        elif event_type == EventType.SPRITE_CHANGED:
            state = (data or {}).get("state")
            if not self._active:
                return
            if state in _PANIC_STATES:
                self._modi_panicked = True
            elif self._modi_panicked and state not in _PANIC_STATES:
                self._begin_exit()   # Modi has calmed -> roach leaves

    def spawn(self):
        if self._active or not self._frames:
            return
        if Config.SELECTED_MASCOT != "modi" or Config.REDUCED_MOTION:
            return
        rect = self._screen()
        # Come from the NEAR side, ROACH_SPAWN_GAP behind Modi: a short approach so
        # he reacts within ~1-2s, and it puts the roach on his tail (he flees the
        # other way, toward the far wall, with room to run).
        modi_center = self._modi_center()
        side = -1 if modi_center < rect.center().x() else 1   # near-wall side
        self._center_x = modi_center + side * ROACH_SPAWN_GAP
        self._active = True
        self._sighted = False
        self._modi_panicked = False
        self._exiting = False
        self._life = 0.0
        self._frame_index = 0
        self._place()
        self.show()
        self.raise_()
        self._clock.restart()
        self._move_timer.start(FRAME_INTERVAL_MS)
        self._anim_timer.start(int(1000 / max(self._fps, 1)))
        logger.info("Roach spawned; chasing Modi.")

    def _begin_exit(self):
        if self._exiting:
            return
        self._exiting = True
        # Head for whichever edge is nearer, away from Modi.
        rect = self._screen()
        self._direction = -1 if self._center_x < rect.center().x() else 1

    def despawn(self):
        self._active = False
        self._move_timer.stop()
        self._anim_timer.stop()
        self.hide()

    # --------------------------------------------------------------------- loop
    def _tick(self):
        if not self._active:
            return
        dt = self._clock.restart() / 1000.0
        dt = min(dt, 0.05)
        self._life += dt
        rect = self._screen()

        if self._exiting:
            self._center_x += ROACH_EXIT_SPEED * self._direction * dt
            self._place()
            off = (self._center_x < rect.left() - self.roach_w or
                   self._center_x > rect.right() + self.roach_w)
            if off:
                self.despawn()
                logger.info("Roach scuttled off-screen.")
            return

        # Safety valve: if Modi never panicked, give up and leave.
        if self._life > _MAX_LIFETIME_SEC:
            self._begin_exit()
            return

        target = self._modi_center()
        dx = target - self._center_x
        dist = abs(dx)
        self._direction = 1 if dx >= 0 else -1

        if dist > _STANDOFF:                 # too far back -> close in
            self._center_x += ROACH_SPEED * self._direction * dt
        elif dist < _STANDOFF - _HYST:       # Modi doubled back -> keep clear
            self._center_x -= ROACH_SPEED * self._direction * dt
        # else: hold the standoff band

        # First time we get close enough while Modi can still be startled.
        if (not self._sighted and dist <= ROACH_SEE_DISTANCE
                and self.pet.renderer.current_state in _VULNERABLE):
            self._sighted = True
            # Hand Modi the roach's position so he can flee the opposite way.
            self.event_bus.publish(EventType.ROACH_SIGHTED, {"roach_x": self._center_x})
            logger.info("Roach reached Modi -> ROACH_SIGHTED.")

        self._place()

    def _place(self):
        rect = self._screen()
        x = int(self._center_x - self.roach_w / 2)
        y = rect.top() + rect.height() - self.roach_h   # stand on the same floor
        self.move(x, y)

    def _advance_frame(self):
        if self._frames:
            self._frame_index = (self._frame_index + 1) % len(self._frames)
            self.update()

    def paintEvent(self, _event):
        if not self._active or not self._frames:
            return
        # Sheet faces RIGHT; use it as-is heading right, mirror heading left.
        frames = self._frames if self._direction == 1 else self._mirrored
        painter = QPainter(self)
        painter.drawPixmap(0, 0, frames[self._frame_index])
        painter.end()
