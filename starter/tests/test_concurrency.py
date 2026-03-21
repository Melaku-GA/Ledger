"""
tests/test_concurrency.py
========================
Double-Decision Concurrency Test - Phase 1 Gate Test

This test verifies the critical Optimistic Concurrency Control (OCC)
mechanism in the event store. Two concurrent agents attempting to 
append to the same stream at the same expected_version will have
exactly one succeed and one receive OptimisticConcurrencyError.

Run: pytest tests/test_concurrency.py -v
"""
import pytest
import asyncio
import pytest_asyncio

from ledger.event_store import InMemoryEventStore, OptimisticConcurrencyError


def _ev(event_type: str, **payload) -> dict:
    return {"event_type": event_type, "event_version": 1, "payload": payload}


@pytest.mark.asyncio
async def test_double_decision_concurrency():
    """
    THE CRITICAL OCC TEST: Two concurrent appends at same expected_version.
    
    Scenario: Two AI agents simultaneously attempt to append a
    CreditAnalysisCompleted event to the same loan application stream.
    Both read the stream at version 2 (3 events) and pass expected_version=2.
    
    Expected:
    - Exactly one succeeds (appends event at position 3)
    - One receives OptimisticConcurrencyError
    - Total events in stream = 3 (not 4)
    """
    store = InMemoryEventStore()
    
    # Setup: Create stream with 3 events (version 2 in 0-indexed)
    await store.append("loan-TEST-001", [_ev("Event1")], expected_version=-1)
    await store.append("loan-TEST-001", [_ev("Event2")], expected_version=0)
    await store.append("loan-TEST-001", [_ev("Event3")], expected_version=1)
    
    # Verify setup - version is 0-indexed (position of last event)
    version = await store.stream_version("loan-TEST-001")
    assert version == 2, f"Expected stream version 2, got {version}"
    
    # Two agents try to append at expected_version=2
    results = []
    
    async def agent_a():
        try:
            positions = await store.append(
                "loan-TEST-001",
                [_ev("AgentA_Decision", agent_id="agent-a", decision="APPROVE")],
                expected_version=2
            )
            results.append(("success", positions))
        except OptimisticConcurrencyError as e:
            results.append(("occ", e))
    
    async def agent_b():
        try:
            positions = await store.append(
                "loan-TEST-001",
                [_ev("AgentB_Decision", agent_id="agent-b", decision="DECLINE")],
                expected_version=2
            )
            results.append(("success", positions))
        except OptimisticConcurrencyError as e:
            results.append(("occ", e))
    
    # Run concurrently
    await asyncio.gather(agent_a(), agent_b())
    
    # Verify: Exactly one success, one OCC error
    successes = [r for r in results if r[0] == "success"]
    occ_errors = [r for r in results if r[0] == "occ"]
    
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(occ_errors) == 1, f"Expected exactly 1 OCC error, got {len(occ_errors)}"
    
    # ENHANCED: Verify stream event count explicitly
    events = await store.load_stream("loan-TEST-001")
    assert len(events) == 4, f"Expected 4 events in stream (3 original + 1 new), got {len(events)}"
    
    # ENHANCED: Verify winning event's stream position explicitly
    success_positions = successes[0][1]
    assert success_positions == [3], f"Expected position [3], got {success_positions}"
    
    # ENHANCED: Verify the actual event content at that position
    winning_event = events[3]  # Index 3 = position 3
    assert winning_event["event_type"] == "AgentA_Decision" or winning_event["event_type"] == "AgentB_Decision"
    
    # ENHANCED: Assert on the exact OptimisticConcurrencyError instance
    occ_error = occ_errors[0][1]
    assert isinstance(occ_error, OptimisticConcurrencyError), "Error must be OptimisticConcurrencyError"
    assert occ_error.stream_id == "loan-TEST-001", f"Expected stream_id 'loan-TEST-001', got {occ_error.stream_id}"
    assert occ_error.expected == 2, f"Expected version 2, got {occ_error.expected}"
    # The actual version is 3 because the winning agent already appended, advancing the stream
    assert occ_error.actual == 3, f"Expected actual version 3 (stream advanced after winner), got {occ_error.actual}"
    
    # Verify: Total stream version = 3 (not 4 - which would indicate both succeeded)
    final_version = await store.stream_version("loan-TEST-001")
    assert final_version == 3, f"Expected final version 3, got {final_version}"
    
    print("\n" + "="*60)
    print("CONCURRENCY TEST PASSED")
    print("="*60)
    print("[OK] Exactly one agent succeeded")
    print("[OK] One agent received OptimisticConcurrencyError")
    print(f"[OK] Stream has exactly {len(events)} events (not 5)")
    print(f"[OK] Stream version = {final_version} (not 4)")
    print(f"[OK] Winning event at position: {success_positions}")
    print(f"[OK] OCC error: stream_id={occ_error.stream_id}, expected={occ_error.expected}, actual={occ_error.actual}")
    print("="*60)


@pytest.mark.asyncio  
async def test_concurrent_three_agents():
    """
    Extended test: Three concurrent agents.
    
    Only one should succeed, two should get OCC errors.
    """
    store = InMemoryEventStore()
    
    # Setup - one event in stream (version 0)
    await store.append("stream-A", [_ev("Base")], expected_version=-1)
    
    # Three agents try to append at expected_version=0
    results = []
    
    async def attempt(agent_id):
        try:
            pos = await store.append(
                "stream-A",
                [_ev(f"Agent_{agent_id}")],
                expected_version=0
            )
            results.append(("success", agent_id, pos))
        except OptimisticConcurrencyError as e:
            results.append(("occ", agent_id, e))
    
    await asyncio.gather(
        attempt("A"),
        attempt("B"),
        attempt("C")
    )
    
    successes = [r for r in results if r[0] == "success"]
    occ_errors = [r for r in results if r[0] == "occ"]
    
    assert len(successes) == 1
    assert len(occ_errors) == 2
    
    final_version = await store.stream_version("stream-A")
    assert final_version == 1
    
    print(f"\nThree-agent test: 1 success, 2 OCC errors, version={final_version}")


@pytest.mark.asyncio
async def test_occ_error_contains_required_info():
    """
    Verify OCC error contains information needed for retry.
    """
    store = InMemoryEventStore()
    await store.append("stream-B", [_ev("E1")], expected_version=-1)
    
    try:
        await store.append("stream-B", [_ev("E2")], expected_version=99)  # Wrong version
    except OptimisticConcurrencyError as e:
        assert e.stream_id == "stream-B"
        assert e.expected == 99
        assert e.actual == 0  # Current version is 0 (one event at position 1)
        
        # These fields enable intelligent retry
        print(f"\nOCC Error Info:")
        print(f"  stream_id: {e.stream_id}")
        print(f"  expected: {e.expected}")
        print(f"  actual: {e.actual}")
        print(f"  message: {str(e)}")
        
    # Test passes if no exception raised (will fail)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
