"""
src/upcasting/registry.py
=========================
Upcaster Registry - Automatic Schema Version Migration

The upcaster registry automatically applies version migrations whenever
old events are loaded from the store. Event loading path must call
the registry transparently - callers never manually invoke upcasters.

Key Features:
- Register upcasters via decorator
- Automatic version chain application
- Immutable stored events (upcasting happens at read time)
"""
from typing import Callable, Optional


class UpcasterRegistry:
    """
    Registry for event upcasters.
    
    Upcasters transform old event structures into new ones at read time,
    without touching the stored events. This is the event sourcing
    solution to schema evolution.
    """
    
    def __init__(self):
        # _upcasters[(event_type, from_version)] = upcaster_function
        self._upcasters: dict[tuple[str, int], Callable[[dict], dict]] = {}
    
    def register(self, event_type: str, from_version: int):
        """
        Decorator to register an upcaster function.
        
        Args:
            event_type: The event type to upcast (e.g., "CreditAnalysisCompleted")
            from_version: The version to upgrade from (e.g., 1 upgrades v1 → v2)
        
        Example:
            @registry.register("CreditAnalysisCompleted", from_version=1)
            def upcast_credit_v1_to_v2(payload: dict) -> dict:
                return {**payload, "new_field": "value"}
        """
        def decorator(fn: Callable[[dict], dict]) -> Callable:
            self._upcasters[(event_type, from_version)] = fn
            return fn
        return decorator
    
    def upcast(self, event: dict) -> dict:
        """
        Apply all registered upcasters for this event type in version order.
        
        This method takes an event and progressively applies all registered
        upcasters to bring it to the latest version.
        
        Args:
            event: The event dict with event_type, event_version, payload
            
        Returns:
            The upcasted event (potentially with new version and payload)
        """
        event_type = event.get("event_type")
        current_version = event.get("event_version", 1)
        payload = event.get("payload", {}).copy()
        new_version = current_version
        
        # Apply upcasters in order: v1→v2, v2→v3, etc.
        v = current_version
        while (event_type, v) in self._upcasters:
            # Apply the upcaster
            payload = self._upcasters[(event_type, v)](payload)
            v += 1
            new_version = v
        
        # Return the upcasted event
        return {
            **event,
            "payload": payload,
            "event_version": new_version,  # Latest version after all upcasters
        }
    
    def get_upcast_chain(self, event_type: str, from_version: int) -> list[Callable]:
        """
        Get the chain of upcasters for an event type starting from a version.
        
        Useful for debugging and documentation.
        """
        chain = []
        v = from_version
        while (event_type, v) in self._upcasters:
            chain.append(self._upcasters[(event_type, v)])
            v += 1
        return chain


# Global registry instance
registry = UpcasterRegistry()


def get_registry() -> UpcasterRegistry:
    """Get the global upcaster registry."""
    return registry
