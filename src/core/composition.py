"""
Composition root: the single place where the application object graph is built.

Ordering rules enforced here (see AUDIT_REPORT.md AV-3/AV-4):
  1. QApplication must exist before this class is constructed.
  2. Everything Qt-related (EventBus, SpriteLoader, StateMachine, PetWindow,
     AIOrchestrator) is constructed on the GUI thread — never on the worker.
  3. The asyncio worker starts first only to run DB init/config overrides
     synchronously; subsystems that publish events start last.
"""
from src.config import Config
from src.event_bus import EventBus, EventType
from src.core.application import Application
from src.core.audio_recorder import AudioRecorder
from src.core.scheduler import AmbientScheduler
from src.storage.db import Database
from src.animation.sprite_loader import SpriteLoader
from src.animation.state_machine import StateMachine
from src.ai.context_engine import ContextEngine
from src.ai.orchestrator import AIOrchestrator
from src.observer.telemetry import TelemetryTracker
from src.observer.win32_hook import Win32Observer
from src.plugins.manager import PluginManager
from src.ui.window import PetWindow
from src.utils.logger import get_logger

logger = get_logger("CompositionRoot")

STARTUP_DB_TIMEOUT_SEC = 10.0


class CompositionRoot:
    """Builds and owns every subsystem. Call on the GUI thread after QApplication exists."""

    def __init__(self):
        logger.info("Building application object graph...")

        Config.validate()

        # 1. Background worker loop (hosts no Qt objects)
        self.application = Application()
        self.application.start()

        # 2. Database schema + persisted config overrides, synchronously,
        #    BEFORE anything reads Config.SELECTED_MASCOT / models.
        self.db = Database(Config.DB_PATH)
        self.application.run_async(self.db.initialize()).result(timeout=STARTUP_DB_TIMEOUT_SEC)
        self.application.run_async(Config.load_db_overrides(self.db)).result(timeout=STARTUP_DB_TIMEOUT_SEC)

        # 3. Event bus — GUI-thread QObject; async deliveries target the worker loop.
        self.event_bus = EventBus()
        self.event_bus.set_async_loop(self.application.loop)

        # 4. GUI-thread subsystems
        self.sprite_loader = SpriteLoader()
        self.state_machine = StateMachine(self.event_bus, self.sprite_loader)
        self.context_engine = ContextEngine()
        self.orchestrator = AIOrchestrator(
            self.event_bus, self.context_engine, self.db, self.application
        )
        self.audio_recorder = AudioRecorder()

        # 5. Worker-loop subsystems (constructed here, run on the worker)
        self.scheduler = AmbientScheduler(self.event_bus, self.db, self.context_engine)
        self.telemetry = TelemetryTracker(self.event_bus, self.db, self.application)

        # 6. Plugins, OS observer, and the global PTT hotkey
        self.plugin_manager = PluginManager(self.event_bus)
        self.observer = Win32Observer(self.event_bus)
        from src.observer.hotkey import GlobalHotkeyListener
        self.hotkey_listener = GlobalHotkeyListener(self.event_bus)

        # 7. Main window last — every subscriber above is registered before
        #    the first event can possibly fire.
        self.window = PetWindow(
            self.event_bus, self.sprite_loader, self.audio_recorder,
            self.db, self.application, self.scheduler
        )

        logger.info("Object graph constructed successfully.")

    def start(self):
        """Starts event-producing subsystems and shows the pet."""
        self.plugin_manager.load_plugins()
        self.telemetry.start()
        self.observer.start()
        self.hotkey_listener.start()
        self.application.run_async(self.scheduler.run())
        self.window.show()
        self.event_bus.publish(EventType.APPLICATION_STARTED, {})
        logger.info("All subsystems started.")

    def shutdown(self):
        """Stops subsystems in reverse dependency order."""
        logger.info("Shutting down subsystems...")
        self.event_bus.publish(EventType.APPLICATION_SHUTTING_DOWN, {})
        self.hotkey_listener.stop()
        self.observer.stop()
        self.audio_recorder.cleanup()
        self.application.shutdown()
        logger.info("Shutdown complete.")
