"""
Process COMP-001 through the Ledger system using PostgreSQL.
This script submits the application and runs it through the full lifecycle.
"""
import asyncio
from src.event_store import EventStore
from src.projections.daemon import ProjectionDaemon
from src.projections.application_summary import ApplicationSummaryProjection
from src.projections.agent_performance import AgentPerformanceLedgerProjection
from src.projections.compliance_audit import ComplianceAuditViewProjection
from src.mcp import tools, resources

class MCPServer:
    """MCP Server that uses PostgreSQL."""
    
    def __init__(self, db_url: str):
        self.store = EventStore(db_url)
        self.app_summary = ApplicationSummaryProjection()
        self.agent_perf = AgentPerformanceLedgerProjection()
        self.compliance = ComplianceAuditViewProjection()
        
        self._projections = {
            "application_summary": self.app_summary,
            "agent_performance": self.agent_perf,
            "compliance_audit": self.compliance,
        }
    
    async def connect(self):
        await self.store.connect()
    
    async def close(self):
        await self.store.close()
    
    async def submit_application(self, **kwargs):
        return await tools.submit_application(self.store, **kwargs)
    
    async def record_credit_analysis(self, **kwargs):
        return await tools.record_credit_analysis(self.store, **kwargs)
    
    async def record_fraud_screening(self, **kwargs):
        return await tools.record_fraud_screening(self.store, **kwargs)
    
    async def record_compliance_check(self, **kwargs):
        return await tools.record_compliance_check(self.store, **kwargs)
    
    async def generate_decision(self, **kwargs):
        return await tools.generate_decision(self.store, **kwargs)
    
    async def record_human_review(self, **kwargs):
        return await tools.record_human_review(self.store, **kwargs)
    
    async def start_agent_session(self, **kwargs):
        return await tools.start_agent_session(self.store, **kwargs)
    
    async def get_application(self, application_id: str):
        return await resources.get_application(self.store, self._projections, application_id)
    
    async def get_application_compliance(self, application_id: str):
        return await resources.get_application_compliance(
            self.store, self._projections, application_id
        )


async def main():
    print("=== Processing COMP-001 through The Ledger (PostgreSQL) ===\n")
    
    # Initialize the MCP server with PostgreSQL
    db_url = "postgresql://postgres:123@localhost:5432/ledger"
    server = MCPServer(db_url)
    await server.connect()
    
    print("Connected to PostgreSQL\n")
    
    # Step 1: Start Agent Session (Gas Town pattern)
    print("Step 1: Starting agent session...")
    result = await server.start_agent_session(
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
    result = await server.submit_application(
        application_id="COMP-001",
        applicant_id="Rodriguez Figueroa and Sanchez",
        requested_amount_usd=500000,
        loan_purpose="working_capital",
        submission_channel="document_upload",
    )
    print(f"  Result: {result}")
    print()
    
    # Step 3: Record Credit Analysis
    print("Step 3: Recording credit analysis...")
    result = await server.record_credit_analysis(
        application_id="COMP-001",
        agent_id="credit-agent-001",
        session_id="comp001-session-001",
        model_version="v2.3",
        confidence_score=0.75,
        risk_tier="MEDIUM",
        recommended_limit_usd=450000,
        input_data={},  # Simplified - just pass empty dict
    )
    print(f"  Result: {result}")
    print()
    
    # Step 4: Start fraud agent session
    print("Step 4: Starting fraud detection agent session...")
    result = await server.start_agent_session(
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
    result = await server.record_fraud_screening(
        application_id="COMP-001",
        agent_id="fraud-agent-001",
        session_id="comp001-fraud-001",
        fraud_score=0.05,
        anomaly_flags=[],
        screening_model_version="v1.5",
        input_data={},  # Simplified
    )
    print(f"  Result: {result}")
    print()
    
    # Step 6: Record Compliance Check
    print("Step 6: Recording compliance check...")
    result = await server.record_compliance_check(
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
    result = await server.generate_decision(
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
    result = await server.record_human_review(
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
    if result.success:
        print(f"  Application ID: {result.data.get('application_id')}")
        print(f"  State: {result.data.get('state')}")
        print(f"  Decision: {result.data.get('decision')}")
    print()
    
    # Step 10: Query compliance
    print("Step 10: Querying compliance record...")
    result = await server.get_application_compliance("COMP-001")
    if result.success:
        print(f"  Checks Passed: {result.data.get('checks_passed')}")
        print(f"  Checks Failed: {result.data.get('checks_failed')}")
    print()
    
    await server.close()
    print("=== COMP-001 Processing Complete ===")

if __name__ == "__main__":
    asyncio.run(main())