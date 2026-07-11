import os
import sys
import importlib.util
from typing import List
from src.event_bus import EventBus
from src.plugins.base import IPlugin
from src.utils.logger import get_logger

logger = get_logger("PluginManager")

class PluginManager:
    """
    Scans the plugins directory, dynamically loads compliant python plugins,
    and hooks them into the central EventBus broker.
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = PluginManager()
        return cls._instance

    def __init__(self):
        self.event_bus = EventBus.get_instance()
        self.loaded_plugins: List[IPlugin] = []
        self.plugins_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src", "plugins"))

    def load_plugins(self):
        """Scans plugins/ directory and dynamically imports and instantiates plugins."""
        logger.info(f"Scanning plugins directory: {self.plugins_dir}")
        if not os.path.exists(self.plugins_dir):
            logger.warning("Plugins directory not found.")
            return

        for filename in os.listdir(self.plugins_dir):
            if filename.endswith(".py") and filename not in ["base.py", "manager.py", "__init__.py"]:
                filepath = os.path.join(self.plugins_dir, filename)
                plugin_name = filename[:-3]
                try:
                    spec = importlib.util.spec_from_file_location(plugin_name, filepath)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        # Register in sys.modules to prevent reload overlaps
                        sys.modules[plugin_name] = module
                        spec.loader.exec_module(module)
                        
                        # Find and load classes matching the IPlugin protocol
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if isinstance(attr, type) and attr_name != "IPlugin":
                                # Duck-type interface validation
                                if hasattr(attr, "get_name") and hasattr(attr, "initialize"):
                                    plugin_instance = attr()
                                    plugin_instance.initialize(self.event_bus)
                                    self.loaded_plugins.append(plugin_instance)
                                    logger.info(f"Loaded plugin successfully: {plugin_instance.get_name()}")
                except Exception as e:
                    logger.error(f"Failed to load plugin {plugin_name} from {filename}: {e}")
