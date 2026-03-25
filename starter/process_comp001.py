"""
Process COMP-001 through the Ledger system.
This script submits the application and runs it through the full lifecycle.
"""
import asyncio
from src.mcp.server import MCPLedgerServer
from src.mcp.tools import submit_application, record_credit_analysis, record_fraud_screening
from src.mcp.tools import record_compliance_check, generate_decision, record_human_review
from src.mcp.tools import start_agent_session

async def main():
    print("=== Processing COMP-001 through The Ledger ===\n")
    
    # Initialize the MCP server
    server = MCPLedgerServer()
    
    # Step 1: Start Agent Session (Gas Town pattern)
    print("Step 1: Starting agent session...")
    result = await start_agent_session(
        store=server.store,
        agent_id="credit-agent-001",
        session_id="comp001-session-001",
        agent_type="CreditAnalysis",
        model_version="v2.3",
        context_source="COMP-001_documents",
        context_token_count=5000,
    )
    print(f"  Result: {result}")
    print()
    
    # Step 2: Submit Application
    print("Step 2: Submitting COMP-001 application...")
    result = await submit_application(
        store=server.store,
        application_id="COMP-001",
        applicant_id="Rodriguez Figueroa and Sanchez",
        requested_amount_usd=500000,  # $500K loan request
        loan_purpose="working_capital",
        submission_channel="document_upload",
    )
    print(f"  Result: {result}")
    print()
    
    # Step 3: Record Credit Analysis
    print("Step 3: Recording credit analysis...")
    result = await record_credit_analysis(
        store=server.store,
        application_id="COMP-001",
        agent_id="credit-agent-001",
        session_id="comp001-session-001",
        model_version="v2.3",
        confidence_score=0.75,
        risk_tier="MEDIUM",
        recommended_limit_usd=450000,
        input_data={
            "company_id": "COMP-001",
            "industry": "construction",
            "revenue": 6376031.96,
            "ebitda": 514335.41,
            "debt_to_equity": 2.32,
            "current_ratio": 1.64,
        },
    )
    print(f"  Result: {result}")
    print()
    
    # Step 4: Start fraud agent session
    print("Step 4: Starting fraud detection agent session...")
    result = await start_agent_session(
        store=server.store,
        agent_id="fraud-agent-001",
        session_id="comp001-fraud-001",
        agent_type="FraudDetection",
        model_version="v1.5",
        context_source="COMP-001_documents",
        context_token_count=3000,
    )
    print(f"  Result: {result}")
    print()
    
    # Step 5: Record Fraud Screening
    print("Step 5: Recording fraud screening...")
    result = await record_fraud_screening(
        store=server.store,
        application_id="COMP-001",
        agent_id="fraud-agent-001",
        session_id="comp001-fraud-001",
        fraud_score=0.05,
        anomaly_flags=[],
        screening_model_version="v1.5",
        input_data={"company_id": "COMP-001"},
    )
    print(f"  Result: {result}")
    print()
    
    # Step 6: Record Compliance Check
    print("Step 6: Recording compliance check...")
    result = await record_compliance_check(
        store=server.store,
        application_id="COMP-001",
        rule_id="KYCU-2026-Q1",
        rule_version="1.0",
        passed=True,
        evidence_hash="abc123",
    )
    print(f"  Result: {result}")
    print()
    
    # Step 7: Generate Decision
    print("Step 7: Generating decision...")
    result = await generate_decision(
        store=server.store,
        application_id="COMP-001",
        orchestrator_agent_id="orchestrator-001",
        confidence_score=0.72,
        recommendation="APPROVE",
        contributing_sessions=["comp001-session-001", "comp001-fraud-001"],
    )
    print(f"  Result: {result}")
    print()
    
    # Step 8: Human Review (auto-approved)
    print("Step 8: Recording human review...")
    result = await record_human_review(
        store=server.store,
        application_id="COMP-001",
        reviewer_id="auto",
        override=False,
        final_decision="APPROVE",
    )
    print(f"  Result: {result}")
    print()
    
    # Step 9: Query the application
    print("Step 9: Querying application state...")
    result = await server.get_application("COMP-001")
    print(f"  Application: {result}")
    print()
    
    # Step 10: Query compliance
    print("Step 10: Querying compliance record...")
    result = await server.get_application_compliance("COMP-001")
    print(f"  Compliance: {result}")
    print()
    
    print("=== COMP-001 Processing Complete ===")

if __name__ == "__main__":
    asyncio.run(main())