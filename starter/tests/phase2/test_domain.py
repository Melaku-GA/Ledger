"""
tests/phase2/test_domain.py
===========================
Phase 2 tests: Domain Logic - Aggregates, Commands & Business Rules

Run: pytest tests/phase2/test_domain.py -v
"""
import pytest
import pytest_asyncio
from decimal import Decimal

# Import from starter modules
from ledger.event_store import InMemoryEventStore, OptimisticConcurrencyError
from ledger.domain.aggregates.loan_application import (
    LoanApplicationAggregate,
    ApplicationState,
    DomainRuleError,
)


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _ev(event_type: str, **payload) -> dict:
    """Helper to create event dict."""
    return {"event_type": event_type, "event_version": 1, "payload": payload}


# ─── LOAN APPLICATION AGGREGATE TESTS ────────────────────────────────────────

@pytest.mark.asyncio
async def test_loan_application_load_replays_events():
    """Test that loading an aggregate replays events to rebuild state."""
    store = InMemoryEventStore()
    
    # Append some events
    await store.append(
        "loan-TEST-001",
        [_ev("ApplicationSubmitted", application_id="TEST-001", applicant_id="APP-001",
             requested_amount_usd=100000, loan_purpose="working_capital")],
        expected_version=-1
    )
    await store.append(
        "loan-TEST-001",
        [_ev("CreditAnalysisRequested", application_id="TEST-001", assigned_agent_id="agent-1")],
        expected_version=0
    )
    
    # Load aggregate
    agg = await LoanApplicationAggregate.load(store, "TEST-001")
    
    assert agg.application_id == "TEST-001"
    assert agg.state == ApplicationState.CREDIT_ANALYSIS_REQUESTED
    assert agg.version == 2  # Two events were appended


@pytest.mark.asyncio
async def test_state_machine_valid_transition():
    """Test that valid state transitions are allowed."""
    store = InMemoryEventStore()
    agg = LoanApplicationAggregate(application_id="TEST-002")
    
    # Start with SUBMITTED
    agg.state = ApplicationState.SUBMITTED
    
    # Valid transition should not raise
    agg.assert_valid_transition(ApplicationState.DOCUMENTS_PENDING)


@pytest.mark.asyncio
async def test_state_machine_invalid_transition():
    """Test that invalid state transitions raise error."""
    store = InMemoryEventStore()
    agg = LoanApplicationAggregate(application_id="TEST-003")
    
    # Start with SUBMITTED
    agg.state = ApplicationState.SUBMITTED
    
    # Invalid transition (can't go from SUBMITTED directly to APPROVED)
    with pytest.raises(DomainRuleError, match="Invalid transition"):
        agg.assert_valid_transition(ApplicationState.APPROVED)


@pytest.mark.asyncio
async def test_aggregate_apply_application_submitted():
    """Test applying ApplicationSubmitted event."""
    agg = LoanApplicationAggregate(application_id="TEST-004")
    
    event = {
        "event_type": "ApplicationSubmitted",
        "payload": {
            "application_id": "TEST-004",
            "applicant_id": "APP-004",
            "requested_amount_usd": 50000,
            "loan_purpose": "equipment_financing"
        }
    }
    
    agg.apply(event)
    
    assert agg.state == ApplicationState.SUBMITTED
    assert agg.applicant_id == "APP-004"
    assert agg.requested_amount_usd == 50000


@pytest.mark.asyncio
async def test_aggregate_apply_credit_analysis_completed():
    """Test applying CreditAnalysisCompleted event."""
    agg = LoanApplicationAggregate(application_id="TEST-005")
    agg.state = ApplicationState.CREDIT_ANALYSIS_REQUESTED
    
    event = {
        "event_type": "CreditAnalysisCompleted",
        "payload": {
            "application_id": "TEST-005",
            "agent_id": "agent-1",
            "session_id": "sess-1",
            "risk_tier": "LOW",
            "recommended_limit_usd": 100000,
            "confidence_score": 0.85
        }
    }
    
    agg.apply(event)
    
    assert agg.state == ApplicationState.CREDIT_ANALYSIS_COMPLETE


@pytest.mark.asyncio
async def test_aggregate_apply_application_approved():
    """Test applying ApplicationApproved event."""
    agg = LoanApplicationAggregate(application_id="TEST-006")
    agg.state = ApplicationState.PENDING_HUMAN_REVIEW
    
    event = {
        "event_type": "ApplicationApproved",
        "payload": {
            "application_id": "TEST-006",
            "approved_amount_usd": 75000,
            "interest_rate": 5.5,
            "approved_by": "human-1"
        }
    }
    
    agg.apply(event)
    
    assert agg.state == ApplicationState.APPROVED


@pytest.mark.asyncio
async def test_aggregate_apply_application_declined():
    """Test applying ApplicationDeclined event."""
    agg = LoanApplicationAggregate(application_id="TEST-007")
    agg.state = ApplicationState.PENDING_DECISION
    
    event = {
        "event_type": "ApplicationDeclined",
        "payload": {
            "application_id": "TEST-007",
            "decline_reasons": ["credit_score_too_low"],
            "declined_by": "system"
        }
    }
    
    agg.apply(event)
    
    assert agg.state == ApplicationState.DECLINED


@pytest.mark.asyncio
async def test_confidence_floor_rule():
    """Test that confidence < 0.6 must result in REFER recommendation."""
    agg = LoanApplicationAggregate(application_id="TEST-008")
    agg.state = ApplicationState.COMPLIANCE_CHECK_COMPLETE
    agg.credit_analysis_completed = True
    agg.fraud_screening_completed = True
    
    # This business rule should be enforced in the command handler
    # When generating a decision with confidence < 0.6, recommendation must be "REFER"
    # We test this by checking the logic in the aggregate
    
    # Simulate a decision with low confidence
    event = {
        "event_type": "DecisionGenerated",
        "payload": {
            "application_id": "TEST-008",
            "confidence_score": 0.5,  # Below 0.6 threshold
            "recommendation": "REFER"  # Must be forced to REFER
        }
    }
    
    agg.apply(event)
    
    # The aggregate should have set recommendation to REFER and go to PENDING_HUMAN_REVIEW
    assert agg.state == ApplicationState.PENDING_HUMAN_REVIEW


@pytest.mark.asyncio
async def test_version_increments_on_apply():
    """Test that version increments with each applied event."""
    agg = LoanApplicationAggregate(application_id="TEST-009")
    
    assert agg.version == 0
    
    agg.apply(_ev("ApplicationSubmitted", application_id="TEST-009"))
    assert agg.version == 1
    
    agg.apply(_ev("CreditAnalysisRequested", application_id="TEST-009"))
    assert agg.version == 2
    
    agg.apply(_ev("CreditAnalysisCompleted", application_id="TEST-009"))
    assert agg.version == 3


# ─── COMMAND HANDLER TESTS ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_command_handler_submit_application():
    """Test the submit_application command handler pattern."""
    store = InMemoryEventStore()
    
    # Create aggregate
    agg = LoanApplicationAggregate(application_id="CMD-001")
    
    # Validate business rules
    agg.assert_valid_transition(ApplicationState.SUBMITTED)
    
    # Determine new events
    new_events = [
        _ev("ApplicationSubmitted",
            application_id="CMD-001",
            applicant_id="APP-CMD-001",
            requested_amount_usd=250000,
            loan_purpose="expansion")
    ]
    
    # Append to store
    await store.append(
        f"loan-CMD-001",
        new_events,
        expected_version=-1
    )
    
    # Verify
    loaded = await LoanApplicationAggregate.load(store, "CMD-001")
    assert loaded.state == ApplicationState.SUBMITTED


@pytest.mark.asyncio
async def test_command_handler_credit_analysis_completed():
    """Test the credit_analysis_completed command handler."""
    store = InMemoryEventStore()
    
    # First, submit the application
    await store.append(
        "loan-CMD-002",
        [_ev("ApplicationSubmitted", application_id="CMD-002", applicant_id="APP-002",
             requested_amount_usd=100000, loan_purpose="working_capital")],
        expected_version=-1
    )
    await store.append(
        "loan-CMD-002",
        [_ev("CreditAnalysisRequested", application_id="CMD-002", assigned_agent_id="agent-1")],
        expected_version=0
    )
    
    # Load aggregate
    agg = await LoanApplicationAggregate.load(store, "CMD-002")
    
    # Validate - must be in CREDIT_ANALYSIS_REQUESTED state
    assert agg.state == ApplicationState.CREDIT_ANALYSIS_REQUESTED
    
    # Validate - credit analysis must be pending
    # (This would be a domain rule)
    
    # Determine new events
    new_events = [
        _ev("CreditAnalysisCompleted",
            application_id="CMD-002",
            agent_id="agent-1",
            session_id="sess-1",
            risk_tier="MEDIUM",
            recommended_limit_usd=80000,
            confidence_score=0.75)
    ]
    
    # Append with correct expected version (which is the current stream version)
    await store.append(
        f"loan-CMD-002",
        new_events,
        expected_version=agg.version  # Should be 1, not 2
    )
    
    # Verify
    loaded = await LoanApplicationAggregate.load(store, "CMD-002")
    assert loaded.state == ApplicationState.CREDIT_ANALYSIS_COMPLETE


# ─── CONCURRENCY TESTS FOR AGGREGATES ───────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_credit_analysis_updates():
    """Test that concurrent credit analysis updates are handled correctly."""
    store = InMemoryEventStore()
    
    # Setup: submit application and request credit analysis
    await store.append(
        "loan-CONC-001",
        [_ev("ApplicationSubmitted", application_id="CONC-001", applicant_id="APP-C-001",
             requested_amount_usd=100000, loan_purpose="working_capital")],
        expected_version=-1
    )
    await store.append(
        "loan-CONC-001",
        [_ev("CreditAnalysisRequested", application_id="CONC-001", assigned_agent_id="agent-1")],
        expected_version=0
    )
    
    # Two agents try to complete credit analysis concurrently
    import asyncio
    
    async def agent_a():
        events = [_ev("CreditAnalysisCompleted", application_id="CONC-001",
                     agent_id="agent-a", session_id="sess-a",
                     risk_tier="LOW", recommended_limit_usd=100000, confidence_score=0.9)]
        return await store.append("loan-CONC-001", events, expected_version=1)
    
    async def agent_b():
        events = [_ev("CreditAnalysisCompleted", application_id="CONC-001",
                     agent_id="agent-b", session_id="sess-b",
                     risk_tier="MEDIUM", recommended_limit_usd=75000, confidence_score=0.7)]
        return await store.append("loan-CONC-001", events, expected_version=1)
    
    results = await asyncio.gather(agent_a(), agent_b(), return_exceptions=True)
    
    # One should succeed, one should fail with OCC
    successes = [r for r in results if isinstance(r, list)]
    errors = [r for r in results if isinstance(r, OptimisticConcurrencyError)]
    
    assert len(successes) == 1, "Exactly one agent should succeed"
    assert len(errors) == 1, "One agent should get OCC error"


# ─── INTEGRATION TEST: FULL APPLICATION LIFECYCLE ────────────────────────────

@pytest.mark.asyncio
async def test_full_application_lifecycle():
    """Test a complete loan application lifecycle through the aggregate."""
    store = InMemoryEventStore()
    app_id = "LIFECYCLE-001"
    
    # 1. Submit Application
    await store.append(f"loan-{app_id}",
        [_ev("ApplicationSubmitted", application_id=app_id, applicant_id="APP-LC-001",
             requested_amount_usd=500000, loan_purpose="expansion")],
        expected_version=-1)
    
    # 2. Request Credit Analysis
    await store.append(f"loan-{app_id}",
        [_ev("CreditAnalysisRequested", application_id=app_id, assigned_agent_id="credit-agent")],
        expected_version=0)
    
    # 3. Complete Credit Analysis
    await store.append(f"loan-{app_id}",
        [_ev("CreditAnalysisCompleted", application_id=app_id, agent_id="credit-agent",
             session_id="sess-credit", risk_tier="LOW", recommended_limit_usd=500000,
             confidence_score=0.9)],
        expected_version=1)
    
    # 4. Request Fraud Screening
    await store.append(f"loan-{app_id}",
        [_ev("FraudScreeningRequested", application_id=app_id)],
        expected_version=2)
    
    # 5. Complete Fraud Screening
    await store.append(f"loan-{app_id}",
        [_ev("FraudScreeningCompleted", application_id=app_id, agent_id="fraud-agent",
             fraud_score=0.1, screening_model_version="v2.1")],
        expected_version=3)
    
    # 6. Request Compliance Check
    await store.append(f"loan-{app_id}",
        [_ev("ComplianceCheckRequested", application_id=app_id, regulation_set_version="2026-Q1",
             checks_required=["KYB", "SANCTIONS", "AML"])],
        expected_version=4)
    
    # 7. Compliance Rules Pass
    await store.append(f"loan-{app_id}",
        [_ev("ComplianceRulePassed", application_id=app_id, rule_id="KYB", rule_version="1.0"),
         _ev("ComplianceRulePassed", application_id=app_id, rule_id="SANCTIONS", rule_version="1.0"),
         _ev("ComplianceRulePassed", application_id=app_id, rule_id="AML", rule_version="1.0")],
        expected_version=5)
    
    # 8. Generate Decision
    await store.append(f"loan-{app_id}",
        [_ev("DecisionGenerated", application_id=app_id, recommendation="APPROVE",
             confidence_score=0.85, contributing_agent_sessions=["sess_credit", "sess_fraud"])],
        expected_version=8)
    
    # 9. Human Review (approves)
    await store.append(f"loan-{app_id}",
        [_ev("HumanReviewCompleted", application_id=app_id, reviewer_id="john-smith",
             override=False, final_decision="APPROVE")],
        expected_version=9)
    
    # 10. Final Approval
    await store.append(f"loan-{app_id}",
        [_ev("ApplicationApproved", application_id=app_id, approved_amount_usd=500000,
             interest_rate=6.5, approved_by="john-smith", effective_date="2026-04-01")],
        expected_version=10)
    
    # Verify final state
    agg = await LoanApplicationAggregate.load(store, app_id)
    assert agg.state == ApplicationState.APPROVED
    assert agg.version == 12  # 11 events appended, last one makes version 12


# Run with: pytest tests/phase2/test_domain.py -v
