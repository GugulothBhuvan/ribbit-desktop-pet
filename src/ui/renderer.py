from typing import List, Optional
from PyQt6.QtGui import QPainter, QPixmap, QTransform, QPen, QColor
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from src.animation.sprite_loader import SpriteLoader
from src.constants import PetState
from src.utils.logger import get_logger

logger = get_logger("SpriteRenderer")

class SpriteRenderer(QObject):
    """
    Manages active frame calculations, state-dependent frame rates,
    horizontal mirroring for left/right movements, and QPainter execution.

    Mirrored frames are built once per animation and cached — the previous
    implementation allocated a transformed QPixmap on every paint while the
    pet faced left (audit perf #2).
    """
    animation_finished = pyqtSignal(str)

    def __init__(self, sprite_loader: SpriteLoader):
        super().__init__()
        self.sprite_loader = sprite_loader

        self.current_state = "idle"   # logical state (drives physics)
        self.animation = "idle"       # animation actually rendered (may be a variant)
        self.frames: List[QPixmap] = []
        self._mirrored_frames: Optional[List[QPixmap]] = None
        self.frame_index = 0
        self.loop = True

        # Mirroring orientation (1 = Right, -1 = Left)
        self.direction = 1

        # Load initial idle frames
        self.set_animation("idle", loop=True)

    def set_animation(self, state: str, loop: bool = True, animation: Optional[str] = None):
        """Loads a new animation sequence and resets frame tracking indices.

        `state` is the logical state (physics reads current_state); `animation`
        is the sprite sequence to render, defaulting to the state name. They
        differ only when a state renders a free-will variant (e.g. WALK shown as
        `walk_bag`)."""
        self.current_state = state
        self.animation = animation or state
        self.frames = self.sprite_loader.get_animation_frames(self.animation)
        self._mirrored_frames = None  # rebuilt lazily for the new frames
        self.frame_index = 0
        self.loop = loop

        if not self.frames:
            logger.warning(f"No frames found for animation: {self.animation}")

    def set_direction(self, direction: int) -> bool:
        """Sets the facing direction (1 right, -1 left). Returns True if changed."""
        if direction == self.direction:
            return False
        self.direction = direction
        return True

    def advance_frame(self) -> bool:
        """Increments the animation frame pointer. Returns True if the visible
        frame changed (so callers can skip redundant repaints)."""
        if not self.frames:
            return False

        # Keep the active animation marked as in-use so the cache purge
        # never evicts what is on screen (audit M-7)
        self.sprite_loader.touch(self.animation)

        previous_index = self.frame_index
        self.frame_index += 1
        if self.frame_index >= len(self.frames):
            if self.loop:
                self.frame_index = 0
            else:
                self.frame_index = len(self.frames) - 1
                self.animation_finished.emit(self.current_state)

        return self.frame_index != previous_index

    def _get_mirrored_frames(self) -> List[QPixmap]:
        if self._mirrored_frames is None:
            transform = QTransform().scale(-1, 1)
            self._mirrored_frames = [f.transformed(transform) for f in self.frames]
        return self._mirrored_frames

    def get_current_frame(self) -> QPixmap:
        """Retrieves the active pixmap frame, mirrored (from cache) if heading left."""
        if not self.frames or self.frame_index >= len(self.frames):
            return QPixmap()

        if self.direction == -1:
            return self._get_mirrored_frames()[self.frame_index]
        return self.frames[self.frame_index]

    def render(self, painter: QPainter):
        """Draws current frame onto the window surface."""
        pixmap = self.get_current_frame()
        if not pixmap.isNull():
            painter.drawPixmap(0, 0, pixmap)
            if self.current_state == PetState.SLEEP:
                self._draw_sleep_zs(painter, pixmap.width())

    # Growing stroke sizes (px) for the floating "Z z z"
    _Z_SIZES = [8, 11, 14]

    def _draw_sleep_zs(self, painter: QPainter, frame_width: int):
        """Floating 'Zzz' rising beside the sleeping pet's head. The sleep
        animation repeats one eyes-closed frame 3x in metadata purely so
        frame_index cycles 0..2 and animates the number of Zs.

        The Zs are drawn as vector strokes (not font glyphs) so they render
        identically everywhere, including fontless offscreen test runs."""
        count = (self.frame_index % 3) + 1
        base_x = int(frame_width * 0.62)
        base_y = 52  # topmost Z stays inside the frame

        for i in range(count):
            size = self._Z_SIZES[i]
            x = base_x + i * 12
            y = base_y - i * 17
            # Dark halo pass then white pass so the Z reads on any wallpaper
            for color, width in ((QColor(35, 35, 45), 4), (QColor(255, 255, 255), 2)):
                pen = QPen(color, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(x, y, x + size, y)                  # top bar
                painter.drawLine(x + size, y, x, y + size)           # diagonal
                painter.drawLine(x, y + size, x + size, y + size)    # bottom bar
