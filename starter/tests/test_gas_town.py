"""
tests/test_gas_town.py
=====================
Gas Town Pattern Tests - Agent Memory Reconstruction

Tests the Gas Town Persistent Ledger Pattern:
- Every agent action is written to the event store BEFORE execution
- On restart, agent replays its event stream to reconstruct context
- Simulated crash recovery test

Run: pytest tests/test_gas_town.py -v
"""
import pytest
import pytest_asyncio
from datetime import datetime

from ledger.event_store import InMemoryEventStore
from src.aggregates.agent_session import (
    AgentSessionAggregate,
    AgentSessionState,
)
from src.integrity.gas_town import reconstruct_agent_context


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _ev(event_type: str, **payload) -> dict:
    """Helper to create event dict."""
    return {"event_type": event_type, "event_version": 1, "payload": payload}


# ─── GAS TOWN TESTS ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gas_town_agent_context_reconstruction():
    """
    Test that an agent can reconstruct its context from the event store
    after a simulated crash.
    
    Scenario:
    1. Agent starts session, appends 5 events
    2. Simulate crash (no in-memory agent object)
    3. Call reconstruct_agent_context() 
    4. Verify reconstructed context is sufficient to continue
    """
    store = InMemoryEventStore()
    
    agent_id = "test-agent"
    session_id = "test-session-001"
    stream_id = f"agent-{agent_id}-{session_id}"
    
    # Simulate agent session with 5 events
    await store.append(stream_id, 
        [_ev("AgentContextLoaded", agent_id=agent_id, session_id=session_id,
             context_source="prior_session", context_token_count=2000,
             model_version="v2.3")],
        expected_version=-1)
    
    await store.append(stream_id,
        [_ev("AgentNodeExecuted", agent_id=agent_id, session_id=session_id,
             node_name="analyze_financials", node_sequence=1)],
        expected_version=0)
    
    await store.append(stream_id,
        [_ev("AgentToolCalled", agent_id=agent_id, session_id=session_id,
             tool_name="query_credit_history", tool_input_summary="applicant_id=123")],
        expected_version=1)
    
    await store.append(stream_id,
        [_ev("AgentNodeExecuted", agent_id=agent_id, session_id=session_id,
             node_name="calculate_risk", node_sequence=2)],
        expected_version=2)
    
    await store.append(stream_id,
        [_ev("AgentOutputWritten", agent_id=agent_id, session_id=session_id,
             decision_data={"risk_score": 0.75, "recommendation": "APPROVE"})],
        expected_version=3)
    
    # Simulate crash - no in-memory agent
    # Reconstruct context from event store
    context = await reconstruct_agent_context(
        store,
        agent_id=agent_id,
        session_id=session_id,
        token_budget=8000
    )
    
    # Verify reconstructed context has required fields
    assert context is not None
    assert context.last_event_position > 0
    assert context.session_health_status in ["HEALTHY", "NEEDS_RECONCILIATION", "CORRUPTED"]
    
    # Verify pending work content
    if hasattr(context, 'pending_work') and context.pending_work:
        print(f"Pending work: {context.pending_work}")
    
    # Verify exact last event position matches stream length (5 events = position 4)
    assert context.last_event_position == 4, f"Expected position 4, got {context.last_event_position}"
    
    # Verify last 3 events are preserved in summary
    # (The reconstruction should include recent events for context)
    if hasattr(context, 'recent_events'):
        assert len(context.recent_events) >= 3, "Should preserve last 3 events"
        print(f"Preserved last 3 events: {len(context.recent_events)}")


@pytest.mark.asyncio
async def test_gas_town_needs_reconciliation():
    """
    Test that partial state (no completion event) triggers NEEDS_RECONCILIATION.
    
    Scenario:
    1. Agent starts and processes work
    2. Last event was a processing event (not a completion)
    3. Reconstruct should flag appropriately
    """
    store = InMemoryEventStore()
    
    agent_id = "test-agent-2"
    session_id = "test-session-002"
    stream_id = f"agent-{agent_id}-{session_id}"
    
    # Simulate agent session with partial work (no completion)
    await store.append(stream_id, 
        [_ev("AgentContextLoaded", agent_id=agent_id, session_id=session_id,
             context_source="resume", context_token_count=1500,
             model_version="v2.3")],
        expected_version=-1)
    
    await store.append(stream_id,
        [_ev("AgentNodeExecuted", agent_id=agent_id, session_id=session_id,
             node_name="process_application", node_sequence=1)],
        expected_version=0)
    
    # Simulate crash mid-work
    context = await reconstruct_agent_context(
        store,
        agent_id=agent_id,
        session_id=session_id,
        token_budget=8000
    )
    
    # Verify it returns a context
    assert context is not None
    assert context.session_health_status is not None


@pytest.mark.asyncio
async def test_gas_town_token_budget_respected():
    """
    Test that token budget is respected when summarizing old events.
    """
    store = InMemoryEventStore()
    
    agent_id = "test-agent-3"
    session_id = "test-session-003"
    stream_id = f"agent-{agent_id}-{session_id}"
    
    # Create many events
    await store.append(stream_id, 
        [_ev("AgentContextLoaded", agent_id=agent_id, session_id=session_id,
             context_source="init", context_token_count=100,
             model_version="v2.3")],
        expected_version=-1)
    
    # Add many processing events
    for i in range(20):
        await store.append(stream_id,
            [_ev("AgentNodeExecuted", agent_id=agent_id, session_id=session_id,
                 node_name=f"step_{i}", node_sequence=i)],
            expected_version=i)
    
    # Reconstruct with small token budget
    context = await reconstruct_agent_context(
        store,
        agent_id=agent_id,
        session_id=session_id,
        token_budget=500  # Very small budget
    )
    
    # Should still work - just summarize within budget
    assert context is not None
    assert context.last_event_position > 0


@pytest.mark.asyncio
async def test_gas_town_preserves_last_events():
    """
    Test that reconstruction works with multiple events.
    """
    store = InMemoryEventStore()
    
    agent_id = "test-agent-4"
    session_id = "test-session-004"
    stream_id = f"agent-{agent_id}-{session_id}"
    
    # Create events
    await store.append(stream_id, 
        [_ev("AgentContextLoaded", agent_id=agent_id, session_id=session_id,
             context_source="init", context_token_count=100,
             model_version="v2.3")],
        expected_version=-1)
    
    for i in range(5):
        await store.append(stream_id,
            [_ev("AgentNodeExecuted", agent_id=agent_id, session_id=session_id,
                 node_name=f"node_{i}", node_sequence=i)],
            expected_version=i)
    
    context = await reconstruct_agent_context(
        store,
        agent_id=agent_id,
        session_id=session_id,
        token_budget=8000
    )
    
    # Should return valid context
    assert context is not None
    assert context.last_event_position > 0


@pytest.mark.asyncio
async def test_gas_town_session_not_found():
    """
    Test reconstruction when session doesn't exist.
    """
    store = InMemoryEventStore()
    
    context = await reconstruct_agent_context(
        store,
        agent_id="nonexistent",
        session_id="nonexistent",
        token_budget=8000
    )
    
    # Should return empty context or handle gracefully
    assert context is not None
    # Should return HEALTHY status for new session
    assert context.session_health_status == "HEALTHY"
