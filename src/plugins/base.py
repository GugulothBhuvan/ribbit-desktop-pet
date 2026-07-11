from typing import Protocol, runtime_checkable

@runtime_checkable
class IPlugin(Protocol):
    """
    Interface definition for custom companion plugins.
    Allows third-party modules to register custom hooks and respond to EventBus broadcasts.
    """
    def get_name(self) -> str:
        """Returns the unique plugin identifier."""
        ...
        
    def initialize(self, event_bus) -> None:
        """Called during application startup to register callbacks on the EventBus."""
        ...
