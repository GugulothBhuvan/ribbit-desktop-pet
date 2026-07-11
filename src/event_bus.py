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

class EventBus(QObject):
    """
    Centralized event bus using PyQt signals.
    Enables asynchronous and thread-safe publish-subscribe pattern across the application.
    """
    event_signal = pyqtSignal(str, dict)
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> "EventBus":
        if cls._instance is None:
            cls._instance = EventBus()
        return cls._instance
    
    def publish(self, event_type: str, data: dict = None):
        """Publish an event to all subscribers."""
        if data is None:
            data = {}
        logger.debug(f"Publishing event: {event_type} with data: {data}")
        self.event_signal.emit(event_type, data)
        
    def subscribe(self, slot):
        """Subscribe a slot (callback) to receive all events."""
        self.event_signal.connect(slot)
        
    def unsubscribe(self, slot):
        """Unsubscribe a slot from the event bus."""
        try:
            self.event_signal.disconnect(slot)
        except TypeError:
            pass
