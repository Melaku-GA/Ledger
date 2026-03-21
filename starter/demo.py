"""
demo.py
=======
Demo script to demonstrate The Ledger - Phase 1 & 2 functionality

Run: python demo.py
"""
import asyncio
import sys

# Add starter to path
sys.path.insert(0, "starter")

from ledger.event_store import InMemoryEventStore, OptimisticConcurrencyError
from ledger.domain.aggregates.loan_application import (
    LoanApplicationAggregate,
    ApplicationState,
)


def _ev(event_type: str, **payload):
    return {"event_type": event_type, "event_version": 1, "payload": payload}


async def demo_1_basic_event_store():
    """Demo 1: Basic Event Store Operations"""
    print("\n" + "="*60)
    print("DEMO 1: Basic Event Store Operations")
    print("="*60)
    
    store = InMemoryEventStore()
    
    # Append first event
    pos = await store.append(
        "loan-DEMO-001",
        [_ev("ApplicationSubmitted", application_id="DEMO-001", 
             applicant_id="ACME Corp", requested_amount_usd=500000)],
        expected_version=-1
    )
    print(f"[OK] Appended ApplicationSubmitted at position: {pos}")
    
    # Get stream version
    version = await store.stream_version("loan-DEMO-001")
    print(f"[OK] Stream version: {version}")
    
    # Load stream
    events = await store.load_stream("loan-DEMO-001")
    print(f"[OK] Loaded {len(events)} event(s) from stream")
    print(f"     - Event 1: {events[0]['event_type']}")
    
    print("\n[DEMO 1 COMPLETE]")


async def demo_2_optimistic_concurrency():
    """Demo 2: Optimistic Concurrency Control"""
    print("\n" + "="*60)
    print("DEMO 2: Optimistic Concurrency Control")
    print("="*60)
    
    store = InMemoryEventStore()
    
    # Setup: Create application with 2 events
    await store.append("loan-DEMO-002", [_ev("AppSubmitted")], expected_version=-1)
    await store.append("loan-DEMO-002", [_ev("CreditAnalysis")], expected_version=0)
    
    print("[OK] Setup: Created stream with 2 events")
    print("[OK] Two agents now attempt to append simultaneously...")
    
    # Two agents try to append at the same time
    results = []
    
    async def agent_a():
        try:
            pos = await store.append(
                "loan-DEMO-002",
                [_ev("AgentA_Complete")],
                expected_version=1
            )
            results.append(("SUCCESS", pos))
        except OptimisticConcurrencyError as e:
            results.append(("OCC_ERROR", str(e)))
    
    async def agent_b():
        try:
            pos = await store.append(
                "loan-DEMO-002",
                [_ev("AgentB_Complete")],
                expected_version=1
            )
            results.append(("SUCCESS", pos))
        except OptimisticConcurrencyError as e:
            results.append(("OCC_ERROR", str(e)))
    
    await asyncio.gather(agent_a(), agent_b())
    
    # Analyze results
    successes = [r for r in results if r[0] == "SUCCESS"]
    occ_errors = [r for r in results if r[0] == "OCC_ERROR"]
    
    print(f"[OK] Results: {len(successes)} success, {len(occ_errors)} OCC errors")
    print(f"     - Winner appended at: {successes[0][1]}")
    print(f"     - Loser got OCC error")
    
    # Verify final state
    final_version = await store.stream_version("loan-DEMO-002")
    print(f"[OK] Final stream version: {final_version} (not 3 - would indicate corruption)")
    
    print("\n[DEMO 2 COMPLETE]")


async def demo_3_aggregate_state_machine():
    """Demo 3: Aggregate State Machine"""
    print("\n" + "="*60)
    print("DEMO 3: Aggregate State Machine")
    print("="*60)
    
    store = InMemoryEventStore()
    
    # Build event history
    app_id = "DEMO-003"
    await store.append(f"loan-{app_id}", 
        [_ev("ApplicationSubmitted", application_id=app_id, applicant_id="TestCorp")], 
        expected_version=-1)
    await store.append(f"loan-{app_id}", 
        [_ev("CreditAnalysisRequested", application_id=app_id)], 
        expected_version=0)
    await store.append(f"loan-{app_id}", 
        [_ev("CreditAnalysisCompleted", application_id=app_id, risk_tier="LOW")], 
        expected_version=1)
    
    # Load aggregate - rebuilds state from events
    agg = await LoanApplicationAggregate.load(store, app_id)
    
    print(f"[OK] Loaded aggregate for application: {agg.application_id}")
    print(f"[OK] Current state: {agg.state.value}")
    print(f"[OK] Applicant: {agg.applicant_id}")
    print(f"[OK] Version: {agg.version} (events replayed)")
    
    # Test valid transition
    try:
        agg.assert_valid_transition(ApplicationState.FRAUD_SCREENING_REQUESTED)
        print("[OK] Valid transition allowed: SUBMITTED -> CREDIT_ANALYSIS_COMPLETE -> FRAUD_SCREENING_REQUESTED")
    except Exception as e:
        print(f"[ERROR] {e}")
    
    # Test invalid transition
    try:
        agg.assert_valid_transition(ApplicationState.APPROVED)
        print("[ERROR] Should have raised exception!")
    except Exception as e:
        print(f"[OK] Invalid transition blocked: Cannot go directly to APPROVED")
    
    print("\n[DEMO 3 COMPLETE]")


async def demo_4_full_lifecycle():
    """Demo 4: Full Application Lifecycle"""
    print("\n" + "="*60)
    print("DEMO 4: Full Application Lifecycle")
    print("="*60)
    
    store = InMemoryEventStore()
    app_id = "DEMO-004"
    
    # Step 1: Submit
    await store.append(f"loan-{app_id}",
        [_ev("ApplicationSubmitted", application_id=app_id, applicant_id="BigCorp", 
             requested_amount_usd=1000000)],
        expected_version=-1)
    print("1. Application Submitted")
    
    # Step 2: Credit Analysis
    await store.append(f"loan-{app_id}",
        [_ev("CreditAnalysisCompleted", application_id=app_id, confidence_score=0.85, 
             risk_tier="LOW", recommended_limit_usd=1000000)],
        expected_version=0)
    print("2. Credit Analysis Complete")
    
    # Step 3: Compliance
    await store.append(f"loan-{app_id}",
        [_ev("ComplianceRulePassed", application_id=app_id, rule_id="KYB")],
        expected_version=1)
    print("3. Compliance Check Passed")
    
    # Step 4: Decision
    await store.append(f"loan-{app_id}",
        [_ev("DecisionGenerated", application_id=app_id, recommendation="APPROVE", 
             confidence_score=0.85)],
        expected_version=2)
    print("4. Decision Generated: APPROVE")
    
    # Step 5: Human Review
    await store.append(f"loan-{app_id}",
        [_ev("HumanReviewCompleted", application_id=app_id, final_decision="APPROVE", 
             reviewer_id="john-smith", override=False)],
        expected_version=3)
    print("5. Human Review Complete")
    
    # Step 6: Final Approval
    await store.append(f"loan-{app_id}",
        [_ev("ApplicationApproved", application_id=app_id, approved_amount_usd=1000000,
             interest_rate=6.5, approved_by="john-smith")],
        expected_version=4)
    print("6. Application APPROVED!")
    
    # Load and verify
    agg = await LoanApplicationAggregate.load(store, app_id)
    print(f"\n[OK] Final State: {agg.state.value}")
    print(f"[OK] Approved Amount: ${agg.approved_amount_usd:,.2f}")
    print(f"[OK] Total Events: {agg.version}")
    
    print("\n[DEMO 4 COMPLETE]")


async def main():
    """Run all demos"""
    print("\n" + "#"*60)
    print("# THE LEDGER - Phase 1 & 2 Demo")
    print("#"*60)
    
    try:
        await demo_1_basic_event_store()
        await demo_2_optimistic_concurrency()
        await demo_3_aggregate_state_machine()
        await demo_4_full_lifecycle()
        
        print("\n" + "#"*60)
        print("# ALL DEMOS COMPLETED SUCCESSFULLY")
        print("#"*60)
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
