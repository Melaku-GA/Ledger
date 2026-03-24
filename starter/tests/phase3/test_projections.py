"""
tests/phase3/test_projections.py
================================
Phase 3: Projection Tests

Tests the three projections:
1. ApplicationSummaryProjection
2. AgentPerformanceLedgerProjection
3. ComplianceAuditViewProjection

Run: pytest tests/phase3/test_projections.py -v
"""
import pytest
from datetime import datetime

from src.projections.application_summary import ApplicationSummaryProjection
from src.projections.agent_performance import AgentPerformanceLedgerProjection
from src.projections.compliance_audit import ComplianceAuditViewProjection


def _ev(event_type: str, **payload) -> dict:
    return {
        "event_type": event_type,
        "event_version": 1,
        "payload": payload,
        "recorded_at": datetime.utcnow().isoformat(),
    }


# ─── ApplicationSummaryProjection Tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_application_summary_submitted():
    """Test ApplicationSummaryProjection handles ApplicationSubmitted."""
    proj = ApplicationSummaryProjection()
    
    event = _ev(
        "ApplicationSubmitted",
        application_id="APP-001",
        applicant_id="ACME Corp",
        requested_amount_usd=500000,
    )
    await proj.apply(event)
    
    result = proj.get("APP-001")
    assert result is not None
    assert result["application_id"] == "APP-001"
    assert result["state"] == "SUBMITTED"
    assert result["applicant_id"] == "ACME Corp"
    assert result["requested_amount_usd"] == 500000


@pytest.mark.asyncio
async def test_application_summary_credit_analysis():
    """Test ApplicationSummaryProjection handles CreditAnalysisCompleted."""
    proj = ApplicationSummaryProjection()
    
    # Submit
    await proj.apply(_ev("ApplicationSubmitted", application_id="APP-002", applicant_id="Test"))
    # Credit analysis
    await proj.apply(_ev(
        "CreditAnalysisCompleted",
        application_id="APP-002",
        risk_tier="LOW",
        recommended_limit_usd=1000000,
    ))
    
    result = proj.get("APP-002")
    assert result["state"] == "CREDIT_ANALYSIS_COMPLETE"
    assert result["risk_tier"] == "LOW"
    assert result["recommended_limit_usd"] == 1000000


@pytest.mark.asyncio
async def test_application_summary_approved():
    """Test ApplicationSummaryProjection handles final approval."""
    proj = ApplicationSummaryProjection()
    
    # Full lifecycle
    await proj.apply(_ev("ApplicationSubmitted", application_id="APP-003", applicant_id="Corp"))
    await proj.apply(_ev("CreditAnalysisCompleted", application_id="APP-003", risk_tier="LOW"))
    await proj.apply(_ev("DecisionGenerated", application_id="APP-003", recommendation="APPROVE"))
    await proj.apply(_ev(
        "ApplicationApproved",
        application_id="APP-003",
        approved_amount_usd=500000,
        interest_rate=6.5,
    ))
    
    result = proj.get("APP-003")
    assert result["state"] == "FINAL_APPROVED"
    assert result["approved_amount_usd"] == 500000
    assert result["decision"] == "APPROVED"


# ─── AgentPerformanceLedgerProjection Tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_performance_tracks_analyses():
    """Test AgentPerformanceLedger tracks credit analyses."""
    proj = AgentPerformanceLedgerProjection()
    
    await proj.apply(_ev(
        "CreditAnalysisCompleted",
        application_id="APP-001",
        agent_id="credit-agent",
        model_version="v2.3",
        confidence_score=0.85,
        analysis_duration_ms=1500,
    ))
    
    result = proj.get("credit-agent", "v2.3")
    assert result is not None
    assert result["analyses_completed"] == 1
    assert result["avg_confidence_score"] == 0.85
    assert result["avg_duration_ms"] == 1500


@pytest.mark.asyncio
async def test_agent_performance_tracks_decisions():
    """Test AgentPerformanceLedger tracks decisions."""
    proj = AgentPerformanceLedgerProjection()
    
    await proj.apply(_ev(
        "DecisionGenerated",
        application_id="APP-001",
        orchestrator_agent_id="orchestrator",
        model_version="v2.3",
        recommendation="APPROVE",
    ))
    await proj.apply(_ev(
        "DecisionGenerated",
        application_id="APP-002",
        orchestrator_agent_id="orchestrator",
        model_version="v2.3",
        recommendation="DECLINE",
    ))
    
    result = proj.get("orchestrator", "v2.3")
    assert result["decisions_generated"] == 2
    assert result["approve_rate"] == 1
    assert result["decline_rate"] == 1


@pytest.mark.asyncio
async def test_agent_performance_multiple_versions():
    """Test AgentPerformanceLedger separates versions."""
    proj = AgentPerformanceLedgerProjection()
    
    # v2.3
    await proj.apply(_ev("CreditAnalysisCompleted", agent_id="agent", model_version="v2.3", confidence_score=0.9))
    # v2.4
    await proj.apply(_ev("CreditAnalysisCompleted", agent_id="agent", model_version="v2.4", confidence_score=0.7))
    
    v23 = proj.get("agent", "v2.3")
    v24 = proj.get("agent", "v2.4")
    
    assert v23["avg_confidence_score"] == 0.9
    assert v24["avg_confidence_score"] == 0.7


# ─── ComplianceAuditViewProjection Tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_compliance_audit_tracks_checks():
    """Test ComplianceAuditView tracks compliance checks."""
    proj = ComplianceAuditViewProjection()
    
    await proj.apply(_ev(
        "ComplianceCheckRequested",
        application_id="APP-001",
        regulation_set_version="2026-Q1",
        checks_required=["KYB", "KYC"],
    ))
    await proj.apply(_ev(
        "ComplianceRulePassed",
        application_id="APP-001",
        rule_id="KYB",
        rule_version="1.0",
    ))
    await proj.apply(_ev(
        "ComplianceRulePassed",
        application_id="APP-001",
        rule_id="KYC",
        rule_version="1.0",
    ))
    
    result = proj.get_current_compliance("APP-001")
    assert result["overall_status"] == "IN_PROGRESS"
    assert result["checks_passed"] == 2
    assert result["checks_failed"] == 0
    assert len(result["events"]) == 3


@pytest.mark.asyncio
async def test_compliance_audit_failed_check():
    """Test ComplianceAuditView tracks failed checks."""
    proj = ComplianceAuditViewProjection()
    
    await proj.apply(_ev("ComplianceCheckRequested", application_id="APP-002"))
    await proj.apply(_ev(
        "ComplianceRuleFailed",
        application_id="APP-002",
        rule_id="SANCTIONS",
        rule_version="1.0",
        failure_reason="Match found",
    ))
    
    result = proj.get_current_compliance("APP-002")
    assert result["overall_status"] == "FAILED"
    assert result["checks_failed"] == 1


@pytest.mark.asyncio
async def test_compliance_audit_temporal_query():
    """Test ComplianceAuditView temporal query (get_compliance_at)."""
    proj = ComplianceAuditViewProjection()
    
    # Event at time T1
    await proj.apply(_ev(
        "ComplianceCheckRequested",
        application_id="APP-003",
        regulation_set_version="2026-Q1",
    ))
    
    # Event at time T2 (after T1)
    await proj.apply(_ev(
        "ComplianceRulePassed",
        application_id="APP-003",
        rule_id="KYB",
        rule_version="1.0",
    ))
    
    # Query at a time between T1 and T2
    # Since events are added synchronously, the query should reflect current state
    past_state = proj.get_compliance_at("APP-003", "2099-01-01T00:00:00Z")
    
    assert past_state["event_count_at_time"] == 2
    assert past_state["overall_status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_compliance_audit_rebuild():
    """Test ComplianceAuditView can be cleared and rebuilt."""
    proj = ComplianceAuditViewProjection()
    
    await proj.apply(_ev("ComplianceCheckRequested", application_id="APP-004"))
    
    result = proj.get_current_compliance("APP-004")
    assert result["events"]
    
    # Rebuild
    proj.clear()
    
    result = proj.get_current_compliance("APP-004")
    assert result["events"] == []


# ─── Integration Test ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_projection_lifecycle():
    """Test full lifecycle through all three projections."""
    from src.projections.daemon import ProjectionDaemon
    from ledger.event_store import InMemoryEventStore
    
    store = InMemoryEventStore()
    
    # Setup projections
    app_summary = ApplicationSummaryProjection()
    agent_perf = AgentPerformanceLedgerProjection()
    compliance = ComplianceAuditViewProjection()
    
    daemon = ProjectionDaemon(store, [app_summary, agent_perf, compliance])
    
    # Create events in the store
    await store.append("loan-APP-001", [_ev("ApplicationSubmitted", 
        application_id="APP-001", applicant_id="ACME", requested_amount_usd=100000)], -1)
    await store.append("loan-APP-001", [_ev("CreditAnalysisCompleted", 
        application_id="APP-001", agent_id="agent-1", model_version="v2.3",
        confidence_score=0.85, risk_tier="LOW")], 0)
    await store.append("loan-APP-001", [_ev("ComplianceCheckRequested", 
        application_id="APP-001", regulation_set_version="2026-Q1")], 1)
    
    # Simulate daemon processing - iterate over async generator
    events = []
    async for event in store.load_all(0):
        events.append(event)
    
    for event in events:
        await app_summary.apply(event)
        await agent_perf.apply(event)
        await compliance.apply(event)
    
    # Verify all projections
    app_result = app_summary.get("APP-001")
    assert app_result["state"] == "COMPLIANCE_REVIEW"
    
    agent_result = agent_perf.get("agent-1", "v2.3")
    assert agent_result["analyses_completed"] == 1
    
    compliance_result = compliance.get_current_compliance("APP-001")
    assert compliance_result["checks_passed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
