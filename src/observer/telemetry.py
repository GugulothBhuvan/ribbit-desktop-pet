import time
from typing import Dict, Any
from src.event_bus import EventBus, EventType
from src.storage.db import Database
from src.core.application import Application
from src.utils.logger import get_logger

logger = get_logger("Telemetry")

class TelemetryTracker:
    """
    Subscribes to EventBus APPLICATION_CHANGED signals.
    Tracks active screen time durations per application and logs them asynchronously to the database.
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "TelemetryTracker":
        if cls._instance is None:
            cls._instance = TelemetryTracker()
        return cls._instance

    def __init__(self):
        self.event_bus = EventBus.get_instance()
        self.db = Database.get_instance()
        
        # State tracking
        self.current_app = ""
        self.current_title = ""
        self.start_time = 0.0
        
        # Subscribe to changes
        self.event_bus.subscribe(self.on_event)

    def start(self):
        self.start_time = time.time()
        logger.info("Telemetry tracking system active.")

    def on_event(self, event_type: str, data: dict):
        if event_type == EventType.APPLICATION_CHANGED:
            new_app = data.get("app_name", "Unknown")
            new_title = data.get("title", "Unknown")
            
            # Log usage for previous application
            if self.current_app:
                duration = int(time.time() - self.start_time)
                if duration > 0:
                    Application.get_instance().run_async(
                        self._save_usage(self.current_app, self.current_title, duration)
                    )
            
            self.current_app = new_app
            self.current_title = new_title
            self.start_time = time.time()
            
        elif event_type == EventType.APPLICATION_SHUTTING_DOWN:
            if self.current_app:
                duration = int(time.time() - self.start_time)
                if duration > 0:
                    Application.get_instance().run_async(
                        self._save_usage(self.current_app, self.current_title, duration)
                    )

    async def _save_usage(self, app_name: str, window_title: str, duration_sec: int):
        """Asynchronously writes duration metrics to application_usage table."""
        try:
            query = """
                INSERT INTO application_usage (app_name, window_title, duration_seconds)
                VALUES (?, ?, ?);
            """
            await self.db.execute_update(query, (app_name, window_title, duration_sec))
            logger.info(f"Telemetry logged: {app_name} -> {duration_sec}s")
        except Exception as e:
            logger.error(f"Failed to save application usage telemetry: {e}")
