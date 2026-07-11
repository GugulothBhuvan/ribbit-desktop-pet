import os
from PyQt6.QtWidgets import QMenu, QApplication
from PyQt6.QtGui import QAction
from src.config import Config
from src.event_bus import EventBus, EventType
from src.storage.db import Database
from src.storage.repository import ConversationRepository, MemoryRepository, SettingsRepository
from src.utils.logger import get_logger

logger = get_logger("ContextMenu")

# Custom styled dark stylesheet for the context menu to enforce premium aesthetics
MENU_STYLESHEET = """
QMenu {
    background-color: #1f1f23;
    color: #e3e3e6;
    border: 1px solid #2d2d30;
    border-radius: 6px;
    padding: 5px 0px;
    font-family: 'Segoe UI', sans-serif;
    font-size: 12px;
}
QMenu::item {
    padding: 6px 24px;
    background-color: transparent;
}
QMenu::item:selected {
    background-color: #3a3a40;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background-color: #2d2d30;
    margin: 4px 8px;
}
"""

class ContextMenu(QMenu):
    """
    Styled context menu triggered on right-clicking the pet.
    Allows adjustment of pet settings, memory clearance, and application shutdown.
    Dependencies (db, application, scheduler) are injected by the CompositionRoot
    via PetWindow.
    """
    def __init__(self, parent_window, event_bus: EventBus, db: Database, application, scheduler):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.event_bus = event_bus
        self.application = application
        self.scheduler = scheduler
        self.setStyleSheet(MENU_STYLESHEET)

        self.conv_repo = ConversationRepository(db)
        self.memory_repo = MemoryRepository(db)
        self.settings_repo = SettingsRepository(db)

        self._init_actions()

    def _init_actions(self):
        # 1. Mascot Customization Submenu
        mascot_menu = self.addMenu("Change Mascot")
        mascot_menu.setStyleSheet(MENU_STYLESHEET)

        sprites_root = os.path.join("assets", "sprites")
        if os.path.exists(sprites_root):
            for folder in os.listdir(sprites_root):
                folder_path = os.path.join(sprites_root, folder)
                if os.path.isdir(folder_path):
                    if os.path.exists(os.path.join(folder_path, "metadata.json")):
                        # Standardize display label
                        label = "Custom Default" if folder == "default" else folder.capitalize()
                        act = QAction(label, self)
                        act.triggered.connect(lambda checked, f=folder: self._on_mascot_changed(f))
                        mascot_menu.addAction(act)

        # 2. AI Provider & Model Submenu
        ai_menu = self.addMenu("AI Model Settings")
        ai_menu.setStyleSheet(MENU_STYLESHEET)

        # Verified against Krutrim /v1/models (2026-07-12). Only non-reasoning
        # models are listed: reasoning models (Qwen3.x, gpt-oss) spend the whole
        # speech-bubble token budget on hidden thinking and reply with nothing.
        models = [
            ("Gemma 4 E4B (Fast)", "gemma-4-E4B-it"),
            ("Gemma 4 26B A4B", "gemma-4-26B-A4B-it"),
            ("Gemma 4 31B", "gemma-4-31b-it"),
        ]
        for label, model_id in models:
            act = QAction(label, self)
            act.triggered.connect(lambda checked, m=model_id: self._on_ai_changed("krutrim", m))
            ai_menu.addAction(act)

        self.addSeparator()

        # 3. Scaling Submenu
        scale_menu = self.addMenu("Adjust Scale")
        scale_menu.setStyleSheet(MENU_STYLESHEET)

        scales = [("0.5x (Small)", 0.5), ("1.0x (Normal)", 1.0), ("1.5x (Large)", 1.5), ("2.0x (Huge)", 2.0)]
        for label, val in scales:
            act = QAction(label, self)
            act.triggered.connect(lambda checked, v=val: self._on_scale_changed(v))
            scale_menu.addAction(act)

        self.addSeparator()

        # 4. Clear Chat History Action
        clear_memory_act = QAction("Clear Memories & Chat History", self)
        clear_memory_act.triggered.connect(self._clear_memories)
        self.addAction(clear_memory_act)

        # 5. Toggle Mute Action
        self.mute_act = QAction("Mute Speech", self, checkable=True)
        self.mute_act.triggered.connect(self._on_mute_toggled)
        self.addAction(self.mute_act)

        # 6. Pomodoro Submenu
        pomo_menu = self.addMenu("Pomodoro Timer")
        pomo_menu.setStyleSheet(MENU_STYLESHEET)

        start_work_act = QAction("Start Work (25 min)", self)
        start_work_act.triggered.connect(self._start_pomo_work)
        pomo_menu.addAction(start_work_act)

        start_break_act = QAction("Start Break (5 min)", self)
        start_break_act.triggered.connect(self._start_pomo_break)
        pomo_menu.addAction(start_break_act)

        stop_pomo_act = QAction("Stop Timer", self)
        stop_pomo_act.triggered.connect(self._stop_pomo)
        pomo_menu.addAction(stop_pomo_act)

        self.addSeparator()

        # 7. Quit Action
        quit_act = QAction("Quit Desktop Pet", self)
        quit_act.triggered.connect(self._on_quit_triggered)
        self.addAction(quit_act)

    def _on_scale_changed(self, scale_val: float):
        logger.info(f"Changing pet scale to {scale_val}")
        self.parent_window.update_scale(scale_val)

    def _on_mascot_changed(self, mascot_name: str):
        logger.info(f"Switching active mascot to: {mascot_name}")
        Config.SELECTED_MASCOT = mascot_name
        self.parent_window.change_mascot(mascot_name)

        # Save setting asynchronously on loop
        self.application.run_async(self.settings_repo.set_setting("SELECTED_MASCOT", mascot_name))

    def _on_ai_changed(self, provider: str, model: str):
        logger.info(f"Switching AI settings: provider={provider}, model={model}")
        Config.LLM_PROVIDER = provider

        if provider == "gemini":
            Config.GEMINI_MODEL = model
            self.application.run_async(self.settings_repo.set_setting("GEMINI_MODEL", model))
        else:
            Config.KRUTRIM_MODEL = model
            self.application.run_async(self.settings_repo.set_setting("KRUTRIM_MODEL", model))

        self.application.run_async(self.settings_repo.set_setting("LLM_PROVIDER", provider))
        self.parent_window.display_speech_bubble(f"AI Provider switched to {provider.upper()} ({model})")

    def _clear_memories(self):
        logger.info("Clearing memory database tables...")
        self.application.run_async(self._db_clear_records())

    async def _db_clear_records(self):
        """Runs on the async worker loop — must not touch UI directly.
        Success feedback is routed back through the event bus (GUI thread)."""
        try:
            await self.conv_repo.clear_history()
            await self.memory_repo.clear_memory()
            logger.info("Chat and facts memory tables cleared.")
            self.event_bus.publish(EventType.SPEECH_REQUESTED, {"text": "Memories cleared successfully!"})
        except Exception as e:
            logger.error(f"Failed to clear database memories: {e}")

    def _on_mute_toggled(self, checked: bool):
        logger.info(f"Mute status: {checked}")
        self.parent_window.set_muted(checked)

    def _on_quit_triggered(self):
        logger.info("Initiating application shutdown...")
        self.event_bus.publish(EventType.APPLICATION_SHUTTING_DOWN, {})
        QApplication.quit()

    def _start_pomo_work(self):
        self.scheduler.pomodoro.start_work(25)
        self.parent_window.display_speech_bubble("Work session started! Focus time!")

    def _start_pomo_break(self):
        self.scheduler.pomodoro.start_break(5)
        self.parent_window.display_speech_bubble("Break session started! Relax.")

    def _stop_pomo(self):
        self.scheduler.pomodoro.stop()
        self.parent_window.display_speech_bubble("Pomodoro timer stopped.")
