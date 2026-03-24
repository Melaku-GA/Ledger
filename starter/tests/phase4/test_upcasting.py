"""
tests/phase4/test_upcasting.py
===============================
Phase 4: Upcasting Tests

Tests the upcaster registry and registered upcasters.

Run: pytest tests/phase4/test_upcasting.py -v
"""
import pytest

from src.upcasting.registry import UpcasterRegistry
from src.upcasting.upcasters import get_upcasted_credit_analysis, get_upcasted_decision


def _ev(event_type: str, event_version: int = 1, **payload) -> dict:
    return {
        "event_type": event_type,
        "event_version": event_version,
        "payload": payload,
    }


# ─── Upcaster Registry Tests ────────────────────────────────────────────────

def test_upcaster_registry_register():
    """Test registering an upcaster."""
    reg = UpcasterRegistry()
    
    @reg.register("TestEvent", from_version=1)
    def upcast_test(payload):
        return {**payload, "upcasted": True}
    
    assert ("TestEvent", 1) in reg._upcasters


def test_upcaster_registry_upcast():
    """Test upcasting an event."""
    reg = UpcasterRegistry()
    
    @reg.register("TestEvent", from_version=1)
    def upcast_test(payload):
        return {**payload, "new_field": "value"}
    
    event = _ev("TestEvent", event_version=1, old_field="data")
    result = reg.upcast(event)
    
    assert result["payload"]["old_field"] == "data"
    assert result["payload"]["new_field"] == "value"
    assert result["event_version"] == 2


def test_upcaster_chain_multiple_versions():
    """Test upcasting through multiple version upgrades."""
    reg = UpcasterRegistry()
    
    @reg.register("MultiVersion", from_version=1)
    def upcast_v1_to_v2(payload):
        return {**payload, "v2": True}
    
    @reg.register("MultiVersion", from_version=2)
    def upcast_v2_to_v3(payload):
        return {**payload, "v3": True}
    
    event = _ev("MultiVersion", event_version=1, v1=True)
    result = reg.upcast(event)
    
    assert result["payload"]["v1"] == True
    assert result["payload"]["v2"] == True
    assert result["payload"]["v3"] == True
    assert result["event_version"] == 3


def test_upcaster_noop_for_unknown():
    """Test that unknown events pass through unchanged."""
    reg = UpcasterRegistry()
    
    event = _ev("UnknownEvent", event_version=1, data="test")
    result = reg.upcast(event)
    
    assert result["payload"]["data"] == "test"
    assert result["event_version"] == 1


# ─── CreditAnalysisCompleted Upcaster Tests ─────────────────────────────────

def test_credit_analysis_v1_to_v2_upcast():
    """Test CreditAnalysisCompleted v1 to v2 upcast."""
    # V1 event (without new fields)
    event = _ev(
        "CreditAnalysisCompleted",
        event_version=1,
        application_id="APP-001",
        agent_id="agent-1",
        session_id="sess-1",
        risk_tier="LOW",
        recommended_limit_usd=500000,
    )
    
    result = get_upcasted_credit_analysis(event)
    
    # Should have new fields added
    assert "model_version" in result["payload"]
    assert "regulatory_basis" in result["payload"]
    # confidence_score was not in v1, should be None
    assert result["payload"]["confidence_score"] is None
    
    # Version should be upgraded
    assert result["event_version"] == 2


def test_credit_analysis_inference_pre_2026():
    """Test model_version inference for pre-2026 events."""
    event = _ev(
        "CreditAnalysisCompleted",
        event_version=1,
        application_id="APP-001",
        agent_id="agent-1",
        recorded_at="2025-06-15T10:00:00Z",  # Pre-2026
    )
    
    result = get_upcasted_credit_analysis(event)
    
    assert result["payload"]["model_version"] == "legacy-pre-2026"


# ─── DecisionGenerated Upcaster Tests ────────────────────────────────────────

def test_decision_v1_to_v2_upcast():
    """Test DecisionGenerated v1 to v2 upcast."""
    event = _ev(
        "DecisionGenerated",
        event_version=1,
        application_id="APP-001",
        orchestrator_agent_id="orchestrator",
        recommendation="APPROVE",
        confidence_score=0.85,
        contributing_agent_sessions=["sess-1", "sess-2"],
    )
    
    result = get_upcasted_decision(event)
    
    # Should have model_versions dict
    assert "model_versions" in result["payload"]
    assert result["event_version"] == 2


# ─── Immutability Test ───────────────────────────────────────────────────────

def test_stored_events_immutable():
    """
    CRITICAL: Test that upcasting does not modify stored events.
    
    This test verifies the core guarantee of event sourcing:
    the stored events are never modified, upcasting happens at read time.
    """
    from src.upcasting.registry import get_registry
    from src.upcasting import upcasters  # Import to register upcasters
    
    # Simulate a stored v1 event
    stored_event = _ev(
        "CreditAnalysisCompleted",
        event_version=1,
        application_id="APP-001",
        agent_id="agent-1",
    )
    
    # Save the original payload
    original_payload = stored_event["payload"].copy()
    
    # Upcast the event (simulating read path)
    reg = get_registry()
    upcasted_event = reg.upcast(stored_event)
    
    # The stored event should be UNCHANGED
    assert stored_event["payload"] == original_payload, "Stored event was modified!"
    
    # The upcasted event should have new fields
    assert "model_version" in upcasted_event["payload"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
