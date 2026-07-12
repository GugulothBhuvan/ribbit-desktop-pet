import time
from src.constants import PetState
from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger
from src.animation.sprite_loader import SpriteLoader

logger = get_logger("StateMachine")

class StateMachine:
    """
    Manages state shifts, validates allowed state transitions, and enforces rules
    such as wake-up sequences and physical interruptions.
    """
    # Events this machine reacts to (all handled on the GUI thread,
    # since state changes drive sprite selection and animation timers).
    SUBSCRIBED_EVENTS = [
        EventType.STATE_TRANSITION_TRIGGERED,
        EventType.PET_DRAGGED,
        EventType.PET_DROPPED,
        EventType.LLM_REQUEST_SENT,
        EventType.VOICE_START_RECORDING,
        EventType.VOICE_STOP_RECORDING,
        EventType.LLM_RESPONSE_RECEIVED,
        EventType.ANIMATION_FINISHED,
    ]

    def __init__(self, event_bus: EventBus, sprite_loader: SpriteLoader):
        self.event_bus = event_bus
        self.sprite_loader = sprite_loader

        self._current_state = PetState.IDLE
        self._state_start_time = time.time()

        for event_type in self.SUBSCRIBED_EVENTS:
            self.event_bus.subscribe(event_type, self.on_event, executor="gui")

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def state_duration(self) -> float:
        return time.time() - self._state_start_time

    def set_state(self, new_state: str) -> bool:
        """Attempts to transition to a new state. Returns True if transition is valid and occurs."""
        if self._current_state == new_state:
            return True
            
        if not self._validate_transition(self._current_state, new_state):
            logger.warning(f"Transition from {self._current_state} -> {new_state} rejected.")
            return False
            
        logger.info(f"State transition: {self._current_state} -> {new_state}")
        self._current_state = new_state
        self._state_start_time = time.time()
        
        # Retrieve sprite attributes
        fps = self.sprite_loader.get_animation_fps(new_state)
        loop = self.sprite_loader.is_looping(new_state)
        
        # Publish event that sprite must update
        self.event_bus.publish(EventType.SPRITE_CHANGED, {
            "state": new_state,
            "fps": fps,
            "loop": loop
        })
        return True

    # States governed by physics; behavior/AI states may not preempt them
    # (prevents fall -> think -> fall flapping when an LLM request lands
    # while the pet is airborne — the bubble still shows regardless).
    PHYSICAL_STATES = [PetState.DRAGGED, PetState.FALL, PetState.LAUNCH, PetState.LANDING]

    def _validate_transition(self, current: str, proposed: str) -> bool:
        """
        Enforces state transition rules.
        - Dragging or gravity drops bypass checks.
        - Physical states can only be exited by physics-driven transitions.
        - Transition protection: Sleep cannot directly transition to Walk.
        """
        # 1. Any state can be interrupted by being dragged, falling, or dropped
        if proposed in [PetState.DRAGGED, PetState.FALL, PetState.LANDING]:
            return True

        # 2. While airborne/dragged, only physics decides the next state
        #    (LANDING -> IDLE via ANIMATION_FINISHED is allowed)
        if current in self.PHYSICAL_STATES:
            if current == PetState.LANDING and proposed == PetState.IDLE:
                return True
            if current == PetState.LAUNCH and proposed == PetState.FALL:
                return True
            return False

        # 3. Enforce sleep wake protection
        if current == PetState.SLEEP:
            # Cannot wake up straight into walking, must sit/wake first
            if proposed in [PetState.WALK, PetState.WAVE, PetState.TALK, PetState.LISTEN]:
                return False

        return True

    def on_event(self, event_type: str, data: dict):
        """Processes signals from the event bus to coordinate transitions."""
        if event_type == EventType.STATE_TRANSITION_TRIGGERED:
            target_state = data.get("state")
            if target_state:
                self.set_state(target_state)
                
        elif event_type == EventType.PET_DRAGGED:
            # Interrupt active states immediately when dragged
            self.set_state(PetState.DRAGGED)
            
        elif event_type == EventType.PET_DROPPED:
            # If dropped, physics determines fall or landing
            is_above_floor = data.get("above_floor", False)
            if is_above_floor:
                self.set_state(PetState.FALL)
            else:
                self.set_state(PetState.LANDING)
                
        elif event_type == EventType.LLM_REQUEST_SENT:
            # Shift to thinking state
            self.set_state(PetState.THINK)
            
        elif event_type == EventType.VOICE_START_RECORDING:
            # Shift to listening state
            self.set_state(PetState.LISTEN)
            
        elif event_type == EventType.VOICE_STOP_RECORDING:
            # While transcription is uploaded, think
            self.set_state(PetState.THINK)
            
        elif event_type == EventType.LLM_RESPONSE_RECEIVED:
            # Once response starts generating/streaming, talk
            self.set_state(PetState.TALK)
            
        elif event_type == EventType.ANIMATION_FINISHED:
            # Loop-once animations notify they have finished
            finished_state = data.get("state")
            if finished_state == self._current_state:
                if finished_state == PetState.LANDING:
                    self.set_state(PetState.IDLE)
                elif finished_state == PetState.CROUCH:
                    # Jump sequence: crouch -> launch -> fall -> landing
                    self.set_state(PetState.LAUNCH)
                elif finished_state == PetState.LAUNCH:
                    self.set_state(PetState.FALL)
                elif finished_state == PetState.WAVE:
                    self.set_state(PetState.IDLE)
