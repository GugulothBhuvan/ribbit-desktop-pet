import time
import random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QElapsedTimer
from PyQt6.QtGui import QPainter, QMouseEvent, QEnterEvent, QGuiApplication
from src.config import Config
from src.constants import (
    PetState, FRAME_INTERVAL_MS, CLICK_DRAG_THRESHOLD_PX, SINGLE_CLICK_DELAY_MS,
    MIN_WANDER_TIME, MAX_WANDER_TIME, MAX_PHYSICS_DT,
    JUMP_IMPULSE, JUMP_FORWARD_SPEED
)
from src.event_bus import EventBus, EventType
from src.physics.movement import MovementController
from src.physics.collision import CollisionResolver
from src.animation.sprite_loader import SpriteLoader
from src.ui.renderer import SpriteRenderer
from src.ui.speech_bubble import SpeechBubble
from src.ui.context_menu import ContextMenu
from src.core.audio_recorder import AudioRecorder
from src.utils.logger import get_logger

logger = get_logger("PetWindow")

class PetWindow(QWidget):
    """
    Main transparent desktop pet window.
    Coordinates the 60Hz physics clock, sprite animation ticks, and mouse interaction events.

    All dependencies are injected by the CompositionRoot; this class owns the
    screen-capture action (single owner) and publishes SCREEN_CAPTURED for the
    orchestrator to consume.
    """

    SUBSCRIBED_EVENTS = [
        EventType.SPRITE_CHANGED,
        EventType.LLM_REQUEST_SENT,
        EventType.LLM_RESPONSE_CHUNK,
        EventType.LLM_RESPONSE_RECEIVED,
        EventType.LLM_ERROR_OCCURRED,
        EventType.PET_DOUBLE_CLICKED,
        EventType.BATTERY_WARNING,
        EventType.WEATHER_FETCHED,
        EventType.POMODORO_WORK_COMPLETE,
        EventType.POMODORO_BREAK_COMPLETE,
        EventType.REMINDER_TRIGGERED,
        EventType.VISION_CAPTURE_REQUESTED,
        EventType.TESTS_PASSED,
        EventType.TESTS_FAILED,
        EventType.SPEECH_REQUESTED,
        EventType.SPEECH_PLAYBACK_STARTED,
        EventType.SPEECH_PLAYBACK_FINISHED,
        EventType.PTT_TOGGLED,
    ]

    def __init__(self, event_bus: EventBus, sprite_loader: SpriteLoader,
                 audio_recorder: AudioRecorder, db, application, scheduler,
                 wake_listener=None, conversation_manager=None):
        super().__init__()
        self.event_bus = event_bus
        self.sprite_loader = sprite_loader
        self.wake_listener = wake_listener
        self.conversation_manager = conversation_manager

        # Subsystems
        self.renderer = SpriteRenderer(sprite_loader)

        # Dimensions matching sprite configurations dynamically from loaded metadata
        self.pet_width = int(sprite_loader.frame_width * Config.ANIMATION_SCALE)
        self.pet_height = int(sprite_loader.frame_height * Config.ANIMATION_SCALE)

        self.is_dragging = False
        self.is_muted = Config.MUTED  # persisted preference
        self.drag_offset = QPoint()
        # Reply held back while waiting for its audio (see _reply_will_be_spoken)
        self._pending_spoken_text = ""

        # Click/drag/double-click discrimination (audit M-2): a press is only a
        # click if the cursor moves < CLICK_DRAG_THRESHOLD_PX; the click action
        # waits SINGLE_CLICK_DELAY_MS for a possible double-click.
        self._pressed = False
        self._suppress_click = False
        self._press_global = QPoint()

        # Hover bookkeeping: resume walking after the cursor leaves (audit m-24)
        self._pre_hover_state = None

        # Cooldown for ambient (non-user-initiated) speech (PRD "Never Spam")
        self._last_ambient_bubble = 0.0

        # Weather policy (plan 6.4): never announce at startup, at most once
        # per session, and only after the app has been up a while
        self._started_at = time.time()
        self._weather_announced = False

        # Initialize UI traits
        self._init_window_properties()

        # Subsystems
        self.physics = MovementController(event_bus, 100.0, 100.0, self.pet_width, self.pet_height)
        self.speech_bubble = SpeechBubble()
        self.speech_bubble.dismissed.connect(self._on_bubble_dismissed)
        self.context_menu = ContextMenu(self, event_bus, db, application, scheduler)
        self.audio_recorder = audio_recorder

        # Deferred single-click action (cancelled by drag or double-click)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_single_click)

        # Event Bus subscriptions (all delivered on the GUI thread)
        for event_type in self.SUBSCRIBED_EVENTS:
            self.event_bus.subscribe(event_type, self.on_event, executor="gui")

        # Timer loops
        # 1. Main 60Hz physics loop. PreciseTimer + a measured dt: default
        #    CoarseTimer drifts ±5% and the old code assumed exactly 60Hz.
        self.physics_timer = QTimer(self)
        self.physics_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.physics_timer.timeout.connect(self._on_physics_tick)
        self.physics_timer.start(FRAME_INTERVAL_MS)
        self._physics_clock = QElapsedTimer()
        self._physics_clock.start()
        self._last_moved_pos = QPoint(-1, -1)
        self._last_direction = 1

        # 2. Animation frame tick timer (FPS-dependent, dynamically scaled)
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._on_animation_tick)
        self._update_animation_fps(self.renderer.current_state)

        # Connect animation finish triggers
        self.renderer.animation_finished.connect(self._on_animation_finished)

        # Position pet on top of primary taskbar floor
        self._initial_spawn_position()

    def _init_window_properties(self):
        # Configure frameless, translucent, stays-on-top, and tool properties
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFixedSize(self.pet_width, self.pet_height)
        self.setMouseTracking(True)

    def _screen_rect(self) -> QRect:
        """Work area of the screen the pet is on.

        QWidget.screen() is genuinely optional — it can return None while the
        widget isn't yet mapped, or if the monitor the pet is standing on gets
        unplugged. Fall back to the primary screen, then to the virtual desktop,
        rather than raising AttributeError mid-physics-tick."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return CollisionResolver.get_virtual_desktop_geometry()
        return screen.availableGeometry()

    def _floor_y(self) -> int:
        """Top-of-taskbar Y for this window's screen (consistent with CollisionResolver)."""
        rect = self._screen_rect()
        return rect.top() + rect.height() - self.pet_height

    def _initial_spawn_position(self):
        # Spawn pet centered at bottom of display floor
        screen_rect = self._screen_rect()
        spawn_x = screen_rect.left() + (screen_rect.width() - self.pet_width) // 2
        spawn_y = self._floor_y()
        self.physics.x = float(spawn_x)
        self.physics.y = float(spawn_y)
        self.move(spawn_x, spawn_y)

    def update_scale(self, scale: float):
        """Dynamic scaling factor resize."""
        self.pet_width = int(self.sprite_loader.frame_width * scale)
        self.pet_height = int(self.sprite_loader.frame_height * scale)
        self.setFixedSize(self.pet_width, self.pet_height)
        self.physics.w = self.pet_width
        self.physics.h = self.pet_height
        self.sprite_loader.set_scale(scale)
        # Recalculate dimensions of active sprite frames
        self.renderer.set_animation(self.renderer.current_state, self.renderer.loop)

    def set_muted(self, muted: bool):
        self.is_muted = muted
        if muted:
            self.speech_bubble.hide()

    def display_speech_bubble(self, text: str, placeholder: bool = False):
        """Renders speech balloon next to pet."""
        if self.is_muted:
            return
        self.speech_bubble.show_text(text, self.pos(), self.pet_width, placeholder=placeholder)

    @staticmethod
    def _reply_will_be_spoken(data: dict) -> bool:
        """True when this reply is also going to TTS, meaning the bubble should
        wait for the audio instead of typing ahead of it. Mirrors the same
        decision TTSManager makes."""
        return bool(data.get("conversational")) and Config.TTS_ENABLED and not Config.MUTED

    def _display_ambient_bubble(self, text: str) -> bool:
        """Shows a bubble for NON-user-initiated speech, subject to the spam
        cooldown (PRD 'Never Spam'). Returns False when suppressed."""
        now = time.time()
        if now - self._last_ambient_bubble < Config.SPEECH_BUBBLE_COOLDOWN_SEC:
            logger.debug(f"Ambient bubble suppressed by cooldown: '{text}'")
            return False
        self._last_ambient_bubble = now
        self.display_speech_bubble(text)
        return True

    def _update_animation_fps(self, state: str):
        # Honor the metadata's per-frame duration (frame 0 to start; the
        # animation tick re-adjusts as frames advance)
        interval = self.sprite_loader.get_frame_duration(state, 0)
        self.anim_timer.start(interval)

    # --- Mouse Event Handlers ---
    # A press is not a drag until the cursor travels CLICK_DRAG_THRESHOLD_PX;
    # a click action is deferred SINGLE_CLICK_DELAY_MS so a double-click can
    # cancel it. Releasing a drag triggers physics only — never a chat query.
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.is_dragging = False
            self._press_global = event.globalPosition().toPoint()
            self.drag_offset = event.position().toPoint()

        elif event.button() == Qt.MouseButton.RightButton:
            # Trigger custom context menu
            self.context_menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent):
        if not (self._pressed and event.buttons() & Qt.MouseButton.LeftButton):
            return

        global_pos = event.globalPosition().toPoint()

        if not self.is_dragging:
            moved = (global_pos - self._press_global).manhattanLength()
            if moved <= CLICK_DRAG_THRESHOLD_PX:
                return
            # Threshold crossed: this press is a drag, not a click
            self.is_dragging = True
            self._click_timer.stop()
            self.physics.start_drag(self.pos() + self.drag_offset)
            self.event_bus.publish(EventType.PET_DRAGGED)

        new_x = global_pos.x() - self.drag_offset.x()
        new_y = global_pos.y() - self.drag_offset.y()

        # Sync directly to physics coordinate values
        self.physics.x = float(new_x)
        self.physics.y = float(new_y)

        # Perform temporary move mapping
        self.move(new_x, new_y)
        self.speech_bubble.position_bubble(self.pos(), self.pet_width)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            return
        self._pressed = False

        if self.is_dragging:
            self.is_dragging = False
            # Drop pet; physics resolves gravity drop or landing bounce
            above_floor = self.pos().y() < self._floor_y()
            self.event_bus.publish(EventType.PET_DROPPED, {"above_floor": above_floor})
        elif self._suppress_click:
            self._suppress_click = False
        else:
            # Defer the click action so a double-click can cancel it
            self._click_timer.start(SINGLE_CLICK_DELAY_MS)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self._pressed = True          # Qt sends a release after this event
            self._suppress_click = True   # ...which must not re-trigger a click
            self.event_bus.publish(EventType.PET_DOUBLE_CLICKED)

    def _on_single_click(self):
        self.event_bus.publish(EventType.PET_CLICKED)
        self._trigger_interaction_loop()

    def _toggle_ptt(self):
        """Global-hotkey push-to-talk toggle (plan 5.6). Replaces the old
        focused-window Space handler, which both required focus the window is
        designed to never take (PRD 8.6) and swallowed the user's spacebar.

        Debounced: defense-in-depth against hotkey auto-repeat/mashing —
        toggling start->stop faster than this produces empty clips anyway."""
        now = time.time()
        if now - getattr(self, "_last_ptt_toggle", 0.0) < 0.4:
            return
        self._last_ptt_toggle = now

        # Hands-free conversation mode: the hotkey starts a session, then VAD
        # handles turn-taking (talk, pause, it replies, listen again). Pressing
        # it again ends the session. This replaces the old record/stop toggle.
        if self.conversation_manager is not None and Config.CONVERSATION_MODE:
            if self.conversation_manager.active:
                logger.info("PTT: ending conversation session.")
            else:
                logger.info("PTT: starting hands-free conversation.")
                self.display_speech_bubble("I'm listening… just talk. (Ctrl+Space to stop)")
            self.conversation_manager.toggle_session()
            return

        # When the wake word owns the mic, the hotkey is a manual "talk now"
        # trigger on that listener — opening a second mic stream here would
        # contend with it. The listener captures a fixed window and emits the
        # same VOICE_RECORD_STOPPED the orchestrator already handles.
        if self.wake_listener is not None and self.wake_listener.active:
            logger.info("PTT: manual trigger via wake-word listener.")
            self.wake_listener.trigger_manual()
            return

        if not self.audio_recorder.is_recording:
            logger.info("PTT: starting audio recording.")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.LISTEN})
            self.event_bus.publish(EventType.VOICE_RECORD_STARTED, {})
            try:
                self.audio_recorder.start_recording()
                self.display_speech_bubble("Listening... (Ctrl+Shift+Space to stop)")
            except Exception as e:
                logger.error(f"Audio recording failed to start: {e}")
                self.display_speech_bubble("I couldn't reach the microphone!")
                self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})
        else:
            logger.info("PTT: stopping audio recording.")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})
            wav_path = self.audio_recorder.stop_recording()
            self.event_bus.publish(EventType.VOICE_RECORD_STOPPED, {"wav_path": wav_path})

    def enterEvent(self, event: QEnterEvent | None):
        """Mouse hover: pause wandering, turn head toward cursor."""
        if event is None:  # Qt's signature is nullable; position() would crash
            return
        if self.renderer.current_state in [PetState.IDLE, PetState.WALK]:
            self._pre_hover_state = self.renderer.current_state
            # Temporarily pause walk behavior
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

            # Determine direction (face mouse)
            direction = -1 if event.position().x() < self.width() / 2 else 1
            if self.renderer.set_direction(direction):
                self.update()

    def leaveEvent(self, event):
        """Resume walking if the hover interrupted a walk."""
        if (self._pre_hover_state == PetState.WALK
                and self.renderer.current_state == PetState.IDLE
                and not self.is_dragging):
            # Give the resumed walk a fresh wander budget, otherwise the
            # expired timer flips it straight back to idle next tick
            self.physics.wander_timer = random.uniform(MIN_WANDER_TIME, MAX_WANDER_TIME)
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.WALK})
        self._pre_hover_state = None

    # --- Game Loops Ticks ---
    def _on_physics_tick(self):
        """60Hz Loop: Updates position vectors and resolves collisions.

        Repaints/moves only when something visible actually changed — the
        unconditional 60Hz repaint was the single largest idle-CPU cost
        (audit perf #1)."""
        dt = min(self._physics_clock.restart() / 1000.0, MAX_PHYSICS_DT)

        new_x, new_y, recommended_state = self.physics.update(
            self.renderer.current_state, self.is_dragging, dt
        )

        needs_repaint = False

        # Apply physics coordinate adjustments only on real movement
        if not self.is_dragging:
            new_pos = QPoint(int(new_x), int(new_y))
            if new_pos != self._last_moved_pos:
                self._last_moved_pos = new_pos
                self.move(new_pos)
                self.speech_bubble.position_bubble(self.pos(), self.pet_width)
                needs_repaint = True

        # Update movement direction in renderer
        if self.renderer.current_state == PetState.WALK:
            if self.renderer.set_direction(self.physics.walk_direction):
                needs_repaint = True

        # Trigger state updates from physics recommendation
        if recommended_state != self.renderer.current_state:
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": recommended_state})
            needs_repaint = True

        if needs_repaint:
            self.update()

    def _on_animation_tick(self):
        """Advances active frame; repaints only when the frame changed."""
        if self.renderer.advance_frame():
            self.update()
        # Honor per-frame durations from metadata
        interval = self.sprite_loader.get_frame_duration(
            self.renderer.current_state, self.renderer.frame_index)
        if interval != self.anim_timer.interval():
            self.anim_timer.start(interval)

    def _on_animation_finished(self, state: str):
        if state == PetState.LAUNCH:
            # Jump: give the pet its upward + forward impulse before the
            # state machine flips LAUNCH -> FALL (gravity shapes the arc)
            self.physics.vy = JUMP_IMPULSE
            self.physics.vx = JUMP_FORWARD_SPEED * self.renderer.direction
        self.event_bus.publish(EventType.ANIMATION_FINISHED, {"state": state})

    def _on_bubble_dismissed(self):
        """When a speech bubble finishes fading, return a talking pet to idle."""
        if self.renderer.current_state == PetState.TALK:
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

    def _trigger_interaction_loop(self):
        """Triggers a witty, developer-themed AI query to display inside bubble."""
        prompts = [
            "Tell me a short, sarcastic developer joke.",
            "Tease me playfully about my uncommitted files.",
            "Ask me what I am programming in a witty, pet-like way.",
            "Give me a short encouragement check about code compilation.",
            "Tease me about bugs or missing semicolons."
        ]
        chosen_prompt = random.choice(prompts)

        pet_status = {
            "x": self.physics.x,
            "y": self.physics.y,
            "state": self.renderer.current_state
        }
        self.event_bus.publish(EventType.CHAT_QUERY_REQUESTED, {
            "prompt": chosen_prompt,
            "pet_state": pet_status
        })

    def on_event(self, event_type: str, data: dict):
        """Listens to EventBus signals (GUI thread)."""
        if event_type == EventType.SPRITE_CHANGED:
            state = data.get("state", "idle")
            loop = data.get("loop", True)
            self.renderer.set_animation(state, loop)
            self._update_animation_fps(state)

        elif event_type == EventType.LLM_REQUEST_SENT:
            # Placeholder: the first streamed chunk replaces it entirely
            self.display_speech_bubble("Thinking...", placeholder=True)

        elif event_type == EventType.LLM_RESPONSE_CHUNK:
            chunk = data.get("text", "")
            if self._reply_will_be_spoken(data):
                # Spoken replies stay on "Thinking..." until the audio actually
                # starts; streaming them now would finish the text seconds
                # before the voice even begins.
                return
            if not self.is_muted:
                self.speech_bubble.append_chunk(chunk, self.pos(), self.pet_width)

        elif event_type == EventType.LLM_RESPONSE_RECEIVED:
            if self._reply_will_be_spoken(data):
                # Hold "Thinking..." — SPEECH_PLAYBACK_STARTED will type this
                # text paced to the voice. Remembered so we can still show it
                # if synthesis fails and no audio ever plays.
                self._pending_spoken_text = data.get("text", "")
                return
            # The text already streamed into the bubble — just let it finish
            # typing and start its dismiss countdown (no re-typing glitch)
            self.speech_bubble.finish_stream()

        elif event_type == EventType.SPEECH_PLAYBACK_STARTED:
            # Audio just began: type the words at exactly the voice's pace.
            self._pending_spoken_text = ""
            text = data.get("text", "")
            if text and not self.is_muted:
                self.speech_bubble.show_text_timed(
                    text, float(data.get("duration_sec", 0.0)),
                    self.pos(), self.pet_width)

        elif event_type == EventType.SPEECH_PLAYBACK_FINISHED:
            # Fallback: synthesis failed, so no audio ever played and the bubble
            # is still on the placeholder. Show the reply at normal speed rather
            # than leaving the user staring at "Thinking...".
            if self._pending_spoken_text:
                self.display_speech_bubble(self._pending_spoken_text)
                self._pending_spoken_text = ""

        elif event_type == EventType.LLM_ERROR_OCCURRED:
            self.display_speech_bubble("I'm having trouble thinking right now.")
            # Transition back to Idle
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

        elif event_type == EventType.SPEECH_REQUESTED:
            # Thread-safe path for any component to request a bubble
            self.display_speech_bubble(data.get("text", ""))

        elif event_type == EventType.PTT_TOGGLED:
            self._toggle_ptt()

        elif event_type == EventType.PET_DOUBLE_CLICKED:
            # Random wave or a real jump (crouch -> launch -> fall -> landing)
            act = random.choice([PetState.WAVE, PetState.CROUCH])
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": act})

        elif event_type == EventType.BATTERY_WARNING:
            percent = data.get("percent", 20)
            if self._display_ambient_bubble(f"My power is running low ({percent}%)! Plug me in soon?"):
                self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})

        elif event_type == EventType.WEATHER_FETCHED:
            # Announce at most once per session, never during the first two
            # minutes (the old behavior greeted every launch with a weather
            # report — audit M-15 / PRD "Never Spam")
            if not self._weather_announced and time.time() - self._started_at > 120.0:
                city = data.get("city", "here")
                temp = data.get("temperature", 20.0)
                desc = data.get("description", "fine")
                if self._display_ambient_bubble(f"It's {temp}°C and {desc} in {city}!"):
                    self._weather_announced = True

        elif event_type == EventType.POMODORO_WORK_COMPLETE:
            self.display_speech_bubble("Work session complete! Time for a break!")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.WAVE})

        elif event_type == EventType.POMODORO_BREAK_COMPLETE:
            self.display_speech_bubble("Break over! Let's get back to work!")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.WAVE})

        elif event_type == EventType.REMINDER_TRIGGERED:
            desc = data.get("description", "time for task")
            self.display_speech_bubble(f"Reminder: {desc}")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.WAVE})

        elif event_type == EventType.VISION_CAPTURE_REQUESTED:
            prompt = data.get("prompt", "Explain what is on my screen in a witty, pet-like way.")
            pet_state = data.get("pet_state", {})
            conversational = data.get("conversational", False)
            self._capture_and_analyze_screen(prompt, pet_state, conversational)

        elif event_type == EventType.TESTS_PASSED:
            if self._display_ambient_bubble("All unit tests passed! Excellent work! 🎉"):
                self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.WAVE})

        elif event_type == EventType.TESTS_FAILED:
            failed_count = data.get("failed_count", 1)
            if self._display_ambient_bubble(f"Oh no, {failed_count} tests failed! Let's fix them."):
                self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})

    def change_mascot(self, mascot_name: str):
        """Swaps active mascot sheet and updates the render frames immediately."""
        self.sprite_loader.set_mascot(mascot_name)

        # Recalculate dimensions dynamically from new mascot metadata!
        self.pet_width = int(self.sprite_loader.frame_width * Config.ANIMATION_SCALE)
        self.pet_height = int(self.sprite_loader.frame_height * Config.ANIMATION_SCALE)
        self.setFixedSize(self.pet_width, self.pet_height)
        self.physics.w = self.pet_width
        self.physics.h = self.pet_height

        self.renderer.set_animation(self.renderer.current_state, self.renderer.loop)

    def _capture_and_analyze_screen(self, prompt: str, pet_state: dict, conversational: bool = False):
        """Prepares the screen capture by hiding visual overlay widgets."""
        logger.info("Starting screen capture routine...")
        self.hide()
        self.speech_bubble.hide()
        # Wait for window manager to register hide and paint desktop
        QTimer.singleShot(250, lambda: self._execute_capture(prompt, pet_state, conversational))

    def _execute_capture(self, prompt: str, pet_state: dict, conversational: bool = False):
        """Grabs the screen and publishes the RAW QImage for the orchestrator.

        Only the grab itself runs here — downscaling and JPEG encoding happen
        on the worker loop (audit M-10: the old full-res PNG encode stalled
        the GUI thread for 100ms+)."""
        try:
            from PyQt6.QtWidgets import QApplication
            # Capture the monitor the PET is sitting on, not always the primary
            # one — on a multi-monitor setup "look at my screen" otherwise only
            # ever showed the laptop, whichever display the pet was on.
            screen = self.screen() or QApplication.primaryScreen()
            if not screen:
                raise RuntimeError("No monitor found to capture.")

            # grabWindow(0) grabs the whole of THIS QScreen. Do NOT pass the
            # screen's geometry as x/y: with window=0 Qt already offsets by the
            # screen's topLeft, so passing it again double-offsets and captures
            # empty space off the desktop edge — a blank grab on every monitor
            # except the primary one (which is at 0,0 and so masked the bug).
            # 0 is Qt's documented "grab the entire screen" window id; PyQt6's
            # stub types the parameter as voidptr and can't express that.
            image = screen.grabWindow(0).toImage()  # pyrefly: ignore[bad-argument-type]
            if image.isNull() or image.width() == 0:
                raise RuntimeError(f"Grab of screen '{screen.name()}' returned no image.")
            logger.info(f"Screen captured from '{screen.name()}': "
                        f"{image.width()}x{image.height()}")

            # Restore pet visibility
            self.show()

            # Trigger custom speech state (THINK)
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})

            # Hand the capture to the orchestrator (single consumer)
            self.event_bus.publish(EventType.SCREEN_CAPTURED, {
                "prompt": prompt,
                "pet_state": pet_state,
                "image": image,
                "conversational": conversational
            })
        except Exception as e:
            logger.error(f"Failed to capture screen: {e}")
            self.show()
            self.display_speech_bubble("Oops! I couldn't look at your screen.")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.renderer.render(painter)

    def closeEvent(self, event):
        self.physics_timer.stop()
        self.anim_timer.stop()
        self._click_timer.stop()
        self.speech_bubble.close()
        super().closeEvent(event)
