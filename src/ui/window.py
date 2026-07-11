import time
import random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPoint, QBuffer, QIODevice
from PyQt6.QtGui import QPainter, QMouseEvent, QEnterEvent, QKeyEvent
from src.config import Config
from src.constants import PetState, FRAME_INTERVAL_MS
from src.event_bus import EventBus, EventType
from src.physics.movement import MovementController
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
    ]

    def __init__(self, event_bus: EventBus, sprite_loader: SpriteLoader,
                 audio_recorder: AudioRecorder, db, application, scheduler):
        super().__init__()
        self.event_bus = event_bus
        self.sprite_loader = sprite_loader

        # Subsystems
        self.renderer = SpriteRenderer(sprite_loader)

        # Dimensions matching sprite configurations dynamically from loaded metadata
        self.pet_width = int(sprite_loader.frame_width * Config.ANIMATION_SCALE)
        self.pet_height = int(sprite_loader.frame_height * Config.ANIMATION_SCALE)

        self.is_dragging = False
        self.is_muted = False
        self.drag_offset = QPoint()

        # Initialize UI traits
        self._init_window_properties()

        # Subsystems
        self.physics = MovementController(event_bus, 100.0, 100.0, self.pet_width, self.pet_height)
        self.speech_bubble = SpeechBubble()
        self.speech_bubble.dismissed.connect(self._on_bubble_dismissed)
        self.context_menu = ContextMenu(self, event_bus, db, application, scheduler)
        self.audio_recorder = audio_recorder

        # Track double click state
        self.last_click_time = 0.0

        # Event Bus subscriptions (all delivered on the GUI thread)
        for event_type in self.SUBSCRIBED_EVENTS:
            self.event_bus.subscribe(event_type, self.on_event, executor="gui")

        # Timer loops
        # 1. Main 60Hz physics & rendering update loop
        self.physics_timer = QTimer(self)
        self.physics_timer.timeout.connect(self._on_physics_tick)
        self.physics_timer.start(FRAME_INTERVAL_MS)

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

    def _initial_spawn_position(self):
        # Spawn pet centered at bottom of display floor
        screen_rect = self.screen().availableGeometry()
        spawn_x = screen_rect.left() + (screen_rect.width() - self.pet_width) // 2
        spawn_y = screen_rect.bottom() - self.pet_height
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

    def display_speech_bubble(self, text: str):
        """Renders speech balloon next to pet."""
        if self.is_muted:
            return
        self.speech_bubble.show_text(text, self.pos(), self.pet_width)

    def _update_animation_fps(self, state: str):
        fps = self.sprite_loader.get_animation_fps(state)
        # Convert FPS to milliseconds interval
        interval = int(1000 / max(fps, 1))
        self.anim_timer.start(interval)

    # --- Mouse Event Handlers ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.drag_offset = event.position().toPoint()
            self.physics.start_drag(self.pos() + self.drag_offset)
            self.event_bus.publish(EventType.PET_DRAGGED)

        elif event.button() == Qt.MouseButton.RightButton:
            # Trigger custom context menu
            self.context_menu.exec(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.is_dragging and event.buttons() == Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            new_x = global_pos.x() - self.drag_offset.x()
            new_y = global_pos.y() - self.drag_offset.y()

            # Sync directly to physics coordinate values
            self.physics.x = float(new_x)
            self.physics.y = float(new_y)

            # Perform temporary move mapping
            self.move(new_x, new_y)
            self.speech_bubble.position_bubble(self.pos(), self.pet_width)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.is_dragging:
            self.is_dragging = False

            # Drop pet; physics resolves gravity drop or landing bounce
            above_floor = self.pos().y() < (self.screen().availableGeometry().bottom() - self.pet_height)
            self.event_bus.publish(EventType.PET_DROPPED, {"above_floor": above_floor})

            # Handle left click dialog trigger (if click duration was very short and no drag offset)
            click_time = time.time()
            if click_time - self.last_click_time < 0.3:
                # Double Click Action
                self.event_bus.publish(EventType.PET_DOUBLE_CLICKED)
            else:
                # Single Click: Trigger AI Dialog
                self._trigger_interaction_loop()

            self.last_click_time = click_time

    def keyPressEvent(self, event: QKeyEvent):
        """PTT: Start recording audio on Spacebar press."""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            logger.info("PTT: Spacebar pressed. Starting audio recording.")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.LISTEN})
            self.event_bus.publish(EventType.VOICE_RECORD_STARTED, {})
            try:
                self.audio_recorder.start_recording()
                self.display_speech_bubble("Listening... (release Spacebar to stop)")
            except Exception as e:
                logger.error(f"Audio recording failed to start: {e}")
                self.display_speech_bubble("I couldn't reach the microphone!")
                self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

    def keyReleaseEvent(self, event: QKeyEvent):
        """PTT: Stop recording and publish voice record stopped event on Spacebar release."""
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            logger.info("PTT: Spacebar released. Stopping audio recording.")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})
            wav_path = self.audio_recorder.stop_recording()
            self.event_bus.publish(EventType.VOICE_RECORD_STOPPED, {"wav_path": wav_path})

    def enterEvent(self, event: QEnterEvent):
        """Mouse hover: pause wandering, turn head toward cursor."""
        if self.renderer.current_state in [PetState.IDLE, PetState.WALK]:
            # Temporarily pause walk behavior
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

            # Determine direction (face mouse)
            cursor_pos = self.mapFromGlobal(self.cursor().pos())
            if cursor_pos.x() < self.width() / 2:
                self.renderer.set_direction(-1) # Face left
            else:
                self.renderer.set_direction(1) # Face right

    def leaveEvent(self, event):
        """Resume normal wander intervals on mouse exit."""
        pass

    # --- Game Loops Ticks ---
    def _on_physics_tick(self):
        """60Hz Loop: Updates position vectors and resolves collisions."""
        new_x, new_y, recommended_state = self.physics.update(
            self.renderer.current_state, self.is_dragging
        )

        # Apply physics coordinate adjustments
        if not self.is_dragging:
            self.move(int(new_x), int(new_y))
            self.speech_bubble.position_bubble(self.pos(), self.pet_width)

        # Update movement direction in renderer
        if self.renderer.current_state == PetState.WALK:
            self.renderer.set_direction(self.physics.walk_direction)

        # Trigger state updates from physics recommendation
        if recommended_state != self.renderer.current_state:
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": recommended_state})

        self.update()  # Repaints widget

    def _on_animation_tick(self):
        """Advances active frame."""
        self.renderer.advance_frame()

    def _on_animation_finished(self, state: str):
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
            self.display_speech_bubble("Thinking...")

        elif event_type == EventType.LLM_RESPONSE_CHUNK:
            chunk = data.get("text", "")
            # Append chunk to bubble streaming display
            self.speech_bubble.append_chunk(chunk, self.pos(), self.pet_width)

        elif event_type == EventType.LLM_RESPONSE_RECEIVED:
            # Set complete final response text
            txt = data.get("text", "")
            self.display_speech_bubble(txt)

        elif event_type == EventType.LLM_ERROR_OCCURRED:
            self.display_speech_bubble("I'm having trouble thinking right now.")
            # Transition back to Idle
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

        elif event_type == EventType.SPEECH_REQUESTED:
            # Thread-safe path for any component to request a bubble
            self.display_speech_bubble(data.get("text", ""))

        elif event_type == EventType.PET_DOUBLE_CLICKED:
            # Play random wave jump
            act = random.choice([PetState.WAVE, PetState.FALL])
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": act})

        elif event_type == EventType.BATTERY_WARNING:
            percent = data.get("percent", 20)
            self.display_speech_bubble(f"My power is running low ({percent}%)! Plug me in soon?")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})

        elif event_type == EventType.WEATHER_FETCHED:
            city = data.get("city", "here")
            temp = data.get("temperature", 20.0)
            desc = data.get("description", "fine")
            self.display_speech_bubble(f"It's {temp}°C and {desc} in {city}!")

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
            self._capture_and_analyze_screen(prompt, pet_state)

        elif event_type == EventType.TESTS_PASSED:
            self.display_speech_bubble("All unit tests passed! Excellent work! 🎉")
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.WAVE})

        elif event_type == EventType.TESTS_FAILED:
            failed_count = data.get("failed_count", 1)
            self.display_speech_bubble(f"Oh no, {failed_count} tests failed! Let's fix them.")
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

    def _capture_and_analyze_screen(self, prompt: str, pet_state: dict):
        """Prepares the screen capture by hiding visual overlay widgets."""
        logger.info("Starting screen capture routine...")
        self.hide()
        self.speech_bubble.hide()
        # Wait for window manager to register hide and paint desktop
        QTimer.singleShot(250, lambda: self._execute_capture(prompt, pet_state))

    def _execute_capture(self, prompt: str, pet_state: dict):
        """Grabs the screen and publishes SCREEN_CAPTURED for the orchestrator."""
        try:
            from PyQt6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if not screen:
                raise RuntimeError("Primary monitor not found.")

            # Perform screen grab
            pixmap = screen.grabWindow(0)

            # Encode as PNG bytes
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            image_bytes = buffer.data().data()

            logger.info(f"Screen capture completed. Byte size: {len(image_bytes)}")

            # Restore pet visibility
            self.show()

            # Trigger custom speech state (THINK)
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})

            # Hand the capture to the orchestrator (single consumer)
            self.event_bus.publish(EventType.SCREEN_CAPTURED, {
                "prompt": prompt,
                "pet_state": pet_state,
                "image_bytes": image_bytes
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
        self.speech_bubble.close()
        super().closeEvent(event)
