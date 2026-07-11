import os
import pytest
from src.event_bus import EventBus, EventType
from src.observer.win32_hook import Win32Observer
from src.observer.telemetry import TelemetryTracker
from src.plugins.manager import PluginManager
from src.plugins.base import IPlugin

def test_observer_initial_state():
    observer = Win32Observer()
    assert observer.is_running is True
    assert observer.is_user_idle is False
    assert observer.prev_app == ""
    assert observer.prev_title == ""

def test_telemetry_subscription():
    tracker = TelemetryTracker.get_instance()
    assert tracker is not None
    assert tracker.current_app == ""
    assert tracker.current_title == ""

def test_plugin_interface_conformance():
    class MockPlugin:
        def get_name(self) -> str:
            return "MockPlugin"
        def initialize(self, event_bus) -> None:
            pass
            
    plugin = MockPlugin()
    assert isinstance(plugin, IPlugin)
    assert plugin.get_name() == "MockPlugin"

def test_plugin_manager_loading():
    manager = PluginManager.get_instance()
    assert manager is not None
    # We should have at least the example plugin loaded if it scanned src/plugins/
    manager.load_plugins()
    assert len(manager.loaded_plugins) > 0
    names = [p.get_name() for p in manager.loaded_plugins]
    assert "ExamplePlugin" in names
