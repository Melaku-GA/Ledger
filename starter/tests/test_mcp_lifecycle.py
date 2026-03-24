"""
tests/test_mcp_lifecycle.py
===========================
Phase 5: MCP Integration Test

Full loan application lifecycle driven entirely through MCP tool calls.
This simulates what a real AI agent would do.

The test:
1. start_agent_session
2. submit_application
3. record_credit_analysis
4. record_fraud_screening
5. record_compliance_check
6. generate_decision
7. record_human_review
8. query ledger://applications/{id}/compliance to verify complete trace

Run: pytest tests/test_mcp_lifecycle.py -v
"""
import pytest
from src.mcp.server import MCPLedgerServer, handle_tool_call, handle_resource_call


@pytest.mark.asyncio
async def test_mcp_full_lifecycle():
    """
    Test full loan application lifecycle via MCP.
    
    This is the critical MCP integration test - demonstrates that
    the entire system can be driven through the MCP interface.
    """
    server = MCPLedgerServer()
    
    # Step 1: Start agent session (Gas Town pattern)
    result = await handle_tool_call("start_agent_session", {
        "agent_id": "credit-agent",
        "session_id": "sess-001",
        "agent_type": "CreditAnalysis",
        "model_version": "v2.3",
        "context_source": "loan_application",
        "context_token_count": 5000,
    }, server)
    
    assert result.success, f"start_agent_session failed: {result.error}"
    print(f"[OK] Agent session started: {result.data}")
    
    # Step 2: Submit application
    result = await handle_tool_call("submit_application", {
        "application_id": "APP-MCP-001",
        "applicant_id": "Acme Corp",
        "requested_amount_usd": 500000,
        "loan_purpose": "Working Capital",
    }, server)
    
    assert result.success, f"submit_application failed: {result.error}"
    print(f"[OK] Application submitted: {result.data}")
    
    # Step 3: Record credit analysis
    result = await handle_tool_call("record_credit_analysis", {
        "application_id": "APP-MCP-001",
        "agent_id": "credit-agent",
        "session_id": "sess-001",
        "model_version": "v2.3",
        "confidence_score": 0.85,
        "risk_tier": "LOW",
        "recommended_limit_usd": 500000,
        "input_data": {"credit_score": 750},
    }, server)
    
    assert result.success, f"record_credit_analysis failed: {result.error}"
    print(f"[OK] Credit analysis recorded: {result.data}")
    
    # Start a session for fraud agent (Gas Town pattern)
    result = await handle_tool_call("start_agent_session", {
        "agent_id": "fraud-agent",
        "session_id": "sess-002",
        "agent_type": "FraudDetection",
        "model_version": "v1.5",
        "context_source": "loan_application",
        "context_token_count": 3000,
    }, server)
    
    assert result.success, f"start_agent_session for fraud failed: {result.error}"
    print(f"[OK] Fraud agent session started: {result.data}")
    
    # Step 4: Record fraud screening
    result = await handle_tool_call("record_fraud_screening", {
        "application_id": "APP-MCP-001",
        "agent_id": "fraud-agent",
        "session_id": "sess-002",
        "fraud_score": 0.1,
        "anomaly_flags": [],
        "screening_model_version": "v1.5",
        "input_data": {},
    }, server)
    
    assert result.success, f"record_fraud_screening failed: {result.error}"
    print(f"[OK] Fraud screening recorded: {result.data}")
    
    # Step 5: Record compliance check
    result = await handle_tool_call("record_compliance_check", {
        "application_id": "APP-MCP-001",
        "rule_id": "KYB",
        "rule_version": "2026-Q1",
        "passed": True,
        "evidence_hash": "abc123",
    }, server)
    
    assert result.success, f"record_compliance_check failed: {result.error}"
    print(f"[OK] Compliance check recorded: {result.data}")
    
    # Step 6: Generate decision
    result = await handle_tool_call("generate_decision", {
        "application_id": "APP-MCP-001",
        "orchestrator_agent_id": "orchestrator",
        "confidence_score": 0.85,
        "recommendation": "APPROVE",
        "contributing_sessions": ["sess-001", "sess-002"],
    }, server)
    
    assert result.success, f"generate_decision failed: {result.error}"
    print(f"[OK] Decision generated: {result.data}")
    
    # Step 7: Record human review
    result = await handle_tool_call("record_human_review", {
        "application_id": "APP-MCP-001",
        "reviewer_id": "john-smith",
        "override": False,
        "final_decision": "APPROVE",
    }, server)
    
    assert result.success, f"record_human_review failed: {result.error}"
    print(f"[OK] Human review recorded: {result.data}")
    
    # Step 8: Query compliance audit view to verify complete trace
    result = await handle_resource_call(
        "ledger://applications/APP-MCP-001/compliance",
        server
    )
    
    assert result.success, f"query_compliance failed: {result.error}"
    print(f"[OK] Compliance audit: {result.data}")
    
    # Verify we have the compliance events
    events = result.data.get("events", [])
    assert len(events) >= 1, f"Expected at least 1 compliance event, got {len(events)}"
    
    # Verify checks passed
    assert result.data.get("checks_passed") == 1
    
    print("\n" + "="*60)
    print("MCP LIFECYCLE TEST PASSED")
    print("="*60)
    print("[OK] Complete loan application driven via MCP tools only")
    print("[OK] All 8 tools executed successfully")
    print("[OK] Compliance audit trail verified via MCP resource")


@pytest.mark.asyncio
async def test_mcp_structured_errors():
    """Test that MCP tools return structured errors."""
    server = MCPLedgerServer()
    
    # Try to record credit analysis without starting session (precondition failure)
    result = await handle_tool_call("record_credit_analysis", {
        "application_id": "APP-ERROR-001",
        "agent_id": "credit-agent",
        "session_id": "sess-new",
        "model_version": "v2.3",
        "confidence_score": 0.85,
        "risk_tier": "LOW",
        "recommended_limit_usd": 500000,
        "input_data": {},
    }, server)
    
    # Should fail with structured error
    assert not result.success
    assert result.error is not None
    assert "error_type" in result.error
    print(f"[OK] Structured error returned: {result.error}")


@pytest.mark.asyncio
async def test_mcp_resources_from_projections():
    """Test that MCP resources read from projections."""
    server = MCPLedgerServer()
    
    # Create an application
    await handle_tool_call("submit_application", {
        "application_id": "APP-RESOURCE-001",
        "applicant_id": "TestCorp",
        "requested_amount_usd": 100000,
        "loan_purpose": "Equipment",
    }, server)
    
    # Query via resource
    result = await handle_resource_call(
        "ledger://applications/APP-RESOURCE-001",
        server
    )
    
    assert result.success
    assert result.data.get("applicant_id") == "TestCorp"
    print(f"[OK] Resource returned from projection: {result.data.get('state')}")


@pytest.mark.asyncio
async def test_mcp_health_endpoint():
    """Test the health endpoint."""
    server = MCPLedgerServer()
    
    result = await handle_resource_call("ledger://ledger/health", server)
    
    assert result.success
    assert "healthy" in result.data
    print(f"[OK] Health check: {result.data}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
