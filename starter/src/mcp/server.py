"""
src/mcp/server.py
=================
MCP Server Entry Point

Exposes The Ledger as a Model Context Protocol server.
Tools (Commands) write events; Resources (Queries) read from projections.
"""
from typing import Any
from ledger.event_store import InMemoryEventStore
from src.projections.daemon import ProjectionDaemon
from src.projections.application_summary import ApplicationSummaryProjection
from src.projections.agent_performance import AgentPerformanceLedgerProjection
from src.projections.compliance_audit import ComplianceAuditViewProjection
from src.mcp import tools, resources


class MCPLedgerServer:
    """
    MCP Server for The Ledger.
    
    Provides:
    - 8 MCP Tools (command side)
    - 6 MCP Resources (query side)
    """
    
    def __init__(self, event_store=None):
        # Initialize event store
        self.store = event_store or InMemoryEventStore()
        
        # Initialize projections
        self.app_summary = ApplicationSummaryProjection()
        self.agent_perf = AgentPerformanceLedgerProjection()
        self.compliance = ComplianceAuditViewProjection()
        
        # Initialize daemon
        self.daemon = ProjectionDaemon(
            self.store,
            [self.app_summary, self.agent_perf, self.compliance],
        )
        
        # Map for resource queries
        self._projections = {
            "application_summary": self.app_summary,
            "agent_performance": self.agent_perf,
            "compliance_audit": self.compliance,
        }
    
    # ─── Tools (Commands) ───────────────────────────────────────────────────
    
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
    
    async def run_integrity_check(self, **kwargs):
        return await tools.run_integrity_check(self.store, **kwargs)
    
    # ─── Resources (Queries) ────────────────────────────────────────────────
    
    async def get_application(self, application_id: str):
        return await resources.get_application(self.store, self._projections, application_id)
    
    async def get_application_compliance(self, application_id: str, as_of: str = None):
        return await resources.get_application_compliance(
            self.store, self._projections, application_id, as_of
        )
    
    async def get_application_audit_trail(self, application_id: str, **kwargs):
        return await resources.get_application_audit_trail(self.store, application_id, **kwargs)
    
    async def get_agent_performance(self, agent_id: str):
        return await resources.get_agent_performance(self._projections, agent_id)
    
    async def get_agent_session(self, agent_id: str, session_id: str):
        return await resources.get_agent_session(self.store, agent_id, session_id)
    
    async def get_ledger_health(self):
        return await resources.get_ledger_health(self.daemon)


# ─── MCP Server Interface (for integration testing) ────────────────────────

async def handle_tool_call(tool_name: str, arguments: dict, server: MCPLedgerServer = None):
    """
    Handle an MCP tool call.
    
    This is the interface for the MCP integration test.
    """
    if server is None:
        server = MCPLedgerServer()
    
    tool_map = {
        "submit_application": server.submit_application,
        "record_credit_analysis": server.record_credit_analysis,
        "record_fraud_screening": server.record_fraud_screening,
        "record_compliance_check": server.record_compliance_check,
        "generate_decision": server.generate_decision,
        "record_human_review": server.record_human_review,
        "start_agent_session": server.start_agent_session,
        "run_integrity_check": server.run_integrity_check,
    }
    
    if tool_name not in tool_map:
        return {"success": False, "error": {"error_type": "UnknownTool", "message": f"Unknown tool: {tool_name}"}}
    
    return await tool_map[tool_name](**arguments)


async def handle_resource_call(resource_uri: str, server: MCPLedgerServer = None):
    """
    Handle an MCP resource call.
    
    This is the interface for the MCP integration test.
    """
    if server is None:
        server = MCPLedgerServer()
    
    # Parse URI
    if resource_uri == "ledger://ledger/health":
        return await server.get_ledger_health()
    
    if resource_uri.startswith("ledger://applications/"):
        # Extract application_id - handle URIs like ledger://applications/APP-MCP-001/compliance
        parts = resource_uri.replace("ledger://applications/", "").split("/")
        app_id = parts[0]
        
        if len(parts) > 1 and parts[1] == "compliance":
            return await server.get_application_compliance(app_id)
        elif len(parts) > 1 and parts[1] == "audit-trail":
            return await server.get_application_audit_trail(app_id)
        else:
            return await server.get_application(app_id)
    
    if resource_uri.startswith("ledger://agents/"):
        parts = resource_uri.split("/")
        agent_id = parts[2]
        
        if len(parts) > 3 and parts[3] == "performance":
            return await server.get_agent_performance(agent_id)
        elif len(parts) > 4 and parts[3] == "sessions":
            session_id = parts[4]
            return await server.get_agent_session(agent_id, session_id)
    
    return {"success": False, "error": {"error_type": "UnknownResource", "message": f"Unknown resource: {resource_uri}"}}
