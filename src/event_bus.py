import threading
from typing import Callable, Dict, List, Optional
import asyncio

from PyQt6.QtCore import QObject, pyqtSignal
from src.utils.logger import get_logger

logger = get_logger("EventBus")


class EventType:
    # Interaction Events
    PET_CLICKED = "PET_CLICKED"
    PET_DOUBLE_CLICKED = "PET_DOUBLE_CLICKED"
    PET_DRAGGED = "PET_DRAGGED"
    PET_DROPPED = "PET_DROPPED"

    # State and Animation Events
    SPRITE_CHANGED = "SPRITE_CHANGED"
    ANIMATION_FINISHED = "ANIMATION_FINISHED"
    STATE_TRANSITION_TRIGGERED = "STATE_TRANSITION_TRIGGERED"

    # Input Processing Events
    VOICE_START_RECORDING = "VOICE_START_RECORDING"
    VOICE_STOP_RECORDING = "VOICE_STOP_RECORDING"
    VOICE_RECEIVED = "VOICE_RECEIVED"
    SCREEN_CAPTURED = "SCREEN_CAPTURED"
    VISION_CAPTURE_REQUESTED = "VISION_CAPTURE_REQUESTED"
    VISION_CAPTURE_COMPLETED = "VISION_CAPTURE_COMPLETED"

    # AI Lifecycle Events
    LLM_REQUEST_SENT = "LLM_REQUEST_SENT"
    LLM_RESPONSE_RECEIVED = "LLM_RESPONSE_RECEIVED"
    LLM_RESPONSE_CHUNK = "LLM_RESPONSE_CHUNK"  # For real-time streaming to bubble
    LLM_ERROR_OCCURRED = "LLM_ERROR_OCCURRED"

    # System Actions
    REMINDER_TRIGGERED = "REMINDER_TRIGGERED"
    APPLICATION_STARTED = "APPLICATION_STARTED"
    APPLICATION_SHUTTING_DOWN = "APPLICATION_SHUTTING_DOWN"
    SPEECH_REQUESTED = "SPEECH_REQUESTED"  # Ask the window to show a bubble (thread-safe path)

    # Ambient & Phase 2 Events
    BATTERY_WARNING = "BATTERY_WARNING"
    WEATHER_FETCHED = "WEATHER_FETCHED"
    POMODORO_WORK_COMPLETE = "POMODORO_WORK_COMPLETE"
    POMODORO_BREAK_COMPLETE = "POMODORO_BREAK_COMPLETE"
    POMODORO_TICK = "POMODORO_TICK"

    # IDE & Workflow Sync Events
    TESTS_PASSED = "TESTS_PASSED"
    TESTS_FAILED = "TESTS_FAILED"

    # Observer Events
    APPLICATION_CHANGED = "APPLICATION_CHANGED"
    USER_IDLE = "USER_IDLE"
    USER_ACTIVE = "USER_ACTIVE"
    SCREEN_STABLE = "SCREEN_STABLE"
    VOICE_RECORD_STARTED = "VOICE_RECORD_STARTED"
    VOICE_RECORD_STOPPED = "VOICE_RECORD_STOPPED"
    CHAT_QUERY_REQUESTED = "CHAT_QUERY_REQUESTED"
    PTT_TOGGLED = "PTT_TOGGLED"  # Global hotkey toggled push-to-talk

    # Hands-free conversation mode
    CONVERSATION_STARTED = "CONVERSATION_STARTED"
    CONVERSATION_ENDED = "CONVERSATION_ENDED"
    # Published the instant audio actually starts, carrying the spoken text and
    # its exact duration so the bubble can type in lockstep with the voice.
    SPEECH_PLAYBACK_STARTED = "SPEECH_PLAYBACK_STARTED"
    # Published when the pet finishes speaking a reply (or has nothing to speak);
    # lets the conversation loop know it's safe to reopen the mic without echo.
    SPEECH_PLAYBACK_FINISHED = "SPEECH_PLAYBACK_FINISHED"


class EventBus(QObject):
    """
    Thread-aware publish/subscribe broker.

    Must be constructed on the GUI thread (it is a QObject whose thread
    affinity determines delivery). Subscribers register per event type with an
    explicit executor:

      - executor="gui":   callback runs on the GUI thread. Publishing from any
                          other thread is safe — delivery is queued through a
                          Qt signal onto the GUI event loop.
      - executor="async": callback runs on the background asyncio worker loop
                          via loop.call_soon_threadsafe.

    This replaces the previous connect-everything-to-one-signal design, which
    silently never delivered events to subscribers registered from the asyncio
    thread (no Qt event loop there to drain the queued connection).
    """
    _gui_dispatch = pyqtSignal(str, dict)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._gui_subs: Dict[str, List[Callable]] = {}
        self._async_subs: Dict[str, List[Callable]] = {}
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._warned_no_loop = False
        self._gui_dispatch.connect(self._on_gui_dispatch)

    def set_async_loop(self, loop: asyncio.AbstractEventLoop):
        """Attach the background asyncio loop used for executor='async' delivery."""
        self._async_loop = loop

    def subscribe(self, event_type: str, callback: Callable[[str, dict], None], executor: str = "gui"):
        """Register a callback for one event type on the given executor."""
        if executor not in ("gui", "async"):
            raise ValueError(f"Unknown executor '{executor}' (expected 'gui' or 'async')")
        with self._lock:
            subs = self._gui_subs if executor == "gui" else self._async_subs
            subs.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: Callable):
        with self._lock:
            for subs in (self._gui_subs, self._async_subs):
                if callback in subs.get(event_type, []):
                    subs[event_type].remove(callback)

    def publish(self, event_type: str, data: dict = None):
        """Publish an event. Safe to call from any thread."""
        if data is None:
            data = {}
        logger.debug(f"Publishing event: {event_type} with data: {data}")

        with self._lock:
            has_gui = bool(self._gui_subs.get(event_type))
            async_callbacks = list(self._async_subs.get(event_type, []))

        if has_gui:
            # Auto connection: direct when emitted on the GUI thread,
            # queued onto the GUI event loop otherwise.
            self._gui_dispatch.emit(event_type, data)

        if async_callbacks:
            loop = self._async_loop
            if loop is None or loop.is_closed():
                if not self._warned_no_loop:
                    self._warned_no_loop = True
                    logger.warning("No async loop attached; async subscribers will not receive events.")
            else:
                for cb in async_callbacks:
                    # Copy data per callback so cross-thread handlers can't
                    # mutate each other's payloads.
                    loop.call_soon_threadsafe(self._safe_invoke, cb, event_type, dict(data))

    def _on_gui_dispatch(self, event_type: str, data: dict):
        with self._lock:
            callbacks = list(self._gui_subs.get(event_type, []))
        for cb in callbacks:
            self._safe_invoke(cb, event_type, data)

    @staticmethod
    def _safe_invoke(callback: Callable, event_type: str, data: dict):
        try:
            callback(event_type, data)
        except Exception:
            logger.exception(f"Subscriber raised while handling {event_type}")
