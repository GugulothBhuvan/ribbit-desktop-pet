import sys
import threading
import asyncio
from typing import Coroutine
from src.config import Config
from src.storage.db import Database
from src.utils.logger import get_logger

logger = get_logger("Application")

class Application:
    """
    Main application engine coordinating background asyncio loop threads
    and orchestrating safe startup and shutdown procedures.
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "Application":
        if cls._instance is None:
            cls._instance = Application()
        return cls._instance

    def __init__(self):
        self.loop_thread: threading.Thread = None
        self.loop: asyncio.AbstractEventLoop = None
        self.is_running = False

    def start(self):
        """Starts the background asynchronous event loop thread."""
        if self.is_running:
            return
            
        logger.info("Initializing application background thread...")
        self.is_running = True
        
        # Setup background loop
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(
            target=self._run_background_loop,
            args=(self.loop,),
            daemon=True,
            name="PetAsyncWorker"
        )
        self.loop_thread.start()
        
        # Run sequential startup: database migrations first, load DB overrides, then start scheduler
        async def startup_sequence():
            await Database.get_instance().initialize()
            await Config.load_db_overrides()
            
            # Start plugins, telemetry, and animation state machine
            from src.plugins.manager import PluginManager
            from src.observer.telemetry import TelemetryTracker
            from src.animation.state_machine import StateMachine
            
            PluginManager.get_instance().load_plugins()
            TelemetryTracker.get_instance().start()
            self.state_machine = StateMachine()

            # Start Win32 Observer QThread
            from src.observer.win32_hook import Win32Observer
            self.observer = Win32Observer()
            self.observer.start()

            from src.core.scheduler import AmbientScheduler
            await AmbientScheduler.get_instance().run()
            
        self.run_async(startup_sequence())

    def _run_background_loop(self, loop: asyncio.AbstractEventLoop):
        asyncio.set_event_loop(loop)
        logger.info("Background asyncio loop thread started.")
        loop.run_forever()

    def run_async(self, coro: Coroutine) -> asyncio.Future:
        """Schedules a coroutine to run on the background event loop thread safely."""
        if not self.is_running or not self.loop:
            logger.error("Cannot run task. Background loop is not active.")
            return None
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def shutdown(self):
        """Cleanly stops the background loop and shuts down the application."""
        if not self.is_running:
            return
            
        logger.info("Stopping background event loop...")
        self.is_running = False
        
        if hasattr(self, "observer") and self.observer:
            self.observer.stop()
            self.observer = None
            
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
            
        if self.loop_thread:
            self.loop_thread.join(timeout=3.0)
            
        logger.info("Application loop shut down successfully.")
