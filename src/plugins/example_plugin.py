from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger("ExamplePlugin")

class ExamplePlugin:
    """
    Simple demonstration plugin that logs application events
    to verify dynamic import and event hooks connectivity.
    """
    def get_name(self) -> str:
        return "ExamplePlugin"
        
    def initialize(self, event_bus: EventBus) -> None:
        event_bus.subscribe(self.on_event)
        logger.info("ExamplePlugin initialized and registered with EventBus.")
        
    def on_event(self, event_type: str, data: dict):
        if event_type == EventType.APPLICATION_CHANGED:
            app_name = data.get("app_name", "Unknown")
            logger.info(f"[Plugin Hook] Active application changed to: {app_name}")
