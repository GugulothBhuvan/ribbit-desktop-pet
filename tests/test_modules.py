import pytest
from src.observer.win32_hook import Win32Observer
from src.observer.telemetry import TelemetryTracker
from src.core.application import Application
from src.plugins.manager import PluginManager
from src.plugins.base import IPlugin

def test_observer_initial_state(event_bus):
    observer = Win32Observer(event_bus)
    assert observer.is_running is True
    assert observer.is_user_idle is False
    assert observer.prev_app == ""
    assert observer.prev_title == ""

def test_telemetry_subscription(event_bus, tmp_db):
    tracker = TelemetryTracker(event_bus, tmp_db, Application())
    assert tracker.current_app == ""
    assert tracker.current_title == ""

@pytest.mark.asyncio
async def test_telemetry_save_usage_writes_row(tmp_db):
    """Regression for audit C-4: _save_usage previously called a nonexistent
    Database method and silently persisted nothing."""
    await tmp_db.initialize()

    tracker = TelemetryTracker.__new__(TelemetryTracker)  # skip event wiring
    tracker.db = tmp_db
    await tracker._save_usage("Code.exe", "main.py - VS Code", 42)

    rows = await tmp_db.execute_query("SELECT app_name, duration_seconds FROM application_usage;")
    assert len(rows) == 1
    assert rows[0]["app_name"] == "Code.exe"
    assert rows[0]["duration_seconds"] == 42

def test_plugin_interface_conformance():
    class MockPlugin:
        def get_name(self) -> str:
            return "MockPlugin"
        def initialize(self, event_bus) -> None:
            pass

    plugin = MockPlugin()
    assert isinstance(plugin, IPlugin)
    assert plugin.get_name() == "MockPlugin"

def test_plugin_manager_loading(event_bus):
    manager = PluginManager(event_bus)
    manager.load_plugins()
    assert len(manager.loaded_plugins) > 0
    names = [p.get_name() for p in manager.loaded_plugins]
    assert "ExamplePlugin" in names
