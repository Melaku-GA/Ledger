"""
src/mcp/resources.py
=====================
MCP Resources - Query side (read operations)

Implements MCP resources for querying projections:
1. ledger://applications/{id} - ApplicationSummary
2. ledger://applications/{id}/compliance - ComplianceAuditView
3. ledger://applications/{id}/audit-trail - AuditLedger stream
4. ledger://agents/{id}/performance - AgentPerformanceLedger
5. ledger://agents/{id}/sessions/{session_id} - AgentSession stream
6. ledger://ledger/health - Projection daemon lags

Key Design:
- All reads from projections (no stream replays except for audit-trail justification)
- SLO: p99 < 50ms for current state, p99 < 200ms for temporal queries
- Temporal query support via ?as_of=timestamp
"""
from typing import Optional
from dataclasses import dataclass


@dataclass
class ResourceResult:
    """Result for MCP resources."""
    success: bool
    data: dict
    error: Optional[dict] = None


# ─── Application Resources ───────────────────────────────────────────────────

async def get_application(
    store,
    projections,
    application_id: str,
) -> ResourceResult:
    """
    Get current application state.
    
    Resource: ledger://applications/{id}
    Source: ApplicationSummary projection, or direct query if projection empty
    SLO: p99 < 50ms
    """
    try:
        app_proj = projections.get("application_summary")
        
        # First check projection
        if app_proj:
            app = app_proj.get(application_id)
            if app:
                return ResourceResult(
                    success=True,
                    data=app
                )
        
        # If projection empty, construct from event stream
        events = await store.load_stream(f"loan-{application_id}")
        
        if not events:
            return ResourceResult(
                success=False,
                data={},
                error={"error_type": "NotFound", "message": f"Application {application_id} not found"}
            )
        
        # Build application view from events
        app_data = {"application_id": application_id, "events": events}
        
        # Extract key fields from events
        for event in events:
            if event.get("event_type") == "ApplicationSubmitted":
                app_data["state"] = "SUBMITTED"
                app_data["applicant_id"] = event.get("payload", {}).get("applicant_id")
                app_data["requested_amount_usd"] = event.get("payload", {}).get("requested_amount_usd")
            elif event.get("event_type") == "DecisionGenerated":
                app_data["decision"] = event.get("payload", {}).get("recommendation")
            elif event.get("event_type") == "HumanReviewCompleted":
                app_data["final_decision"] = event.get("payload", {}).get("final_decision")
                app_data["reviewer_id"] = event.get("payload", {}).get("reviewer_id")
        
        return ResourceResult(
            success=True,
            data=app_data
        )
    except Exception as e:
        return ResourceResult(
            success=False,
            data={},
            error={"error_type": "QueryError", "message": str(e)}
        )


async def get_application_compliance(
    store,
    projections,
    application_id: str,
    as_of: Optional[str] = None,
) -> ResourceResult:
    """
    Get compliance audit view for an application.
    
    Resource: ledger://applications/{id}/compliance
    Source: ComplianceAuditView projection, or direct query if projection empty
    SLO: p99 < 200ms
    
    Supports temporal query: ?as_of=timestamp
    """
    try:
        compliance_proj = projections.get("compliance_audit")
        
        # First check projection
        if compliance_proj:
            if as_of:
                # Temporal query
                result = compliance_proj.get_compliance_at(application_id, as_of)
            else:
                # Current state
                result = compliance_proj.get_current_compliance(application_id)
            
            if result and (result.get("event_count_at_time", 0) > 0 or result.get("checks_passed", 0) > 0):
                return ResourceResult(
                    success=True,
                    data=result
                )
        
        # If projection empty, construct compliance view from event stream
        events = await store.load_stream(f"loan-{application_id}")
        
        compliance_events = [
            e for e in events 
            if e.get("event_type") in ["ComplianceRulePassed", "ComplianceRuleFailed"]
        ]
        
        if not compliance_events:
            return ResourceResult(
                success=False,
                data={},
                error={"error_type": "NotFound", "message": f"Compliance record for {application_id} not found"}
            )
        
        # Build compliance view from events
        checks_passed = sum(1 for e in compliance_events if e.get("event_type") == "ComplianceRulePassed")
        checks_failed = sum(1 for e in compliance_events if e.get("event_type") == "ComplianceRuleFailed")
        
        return ResourceResult(
            success=True,
            data={
                "application_id": application_id,
                "checks_passed": checks_passed,
                "checks_failed": checks_failed,
                "total_checks": len(compliance_events),
                "events": compliance_events,
            }
        )
    except Exception as e:
        return ResourceResult(
            success=False,
            data={},
            error={"error_type": "QueryError", "message": str(e)}
        )


async def get_application_audit_trail(
    store,
    application_id: str,
    from_position: Optional[int] = None,
    to_position: Optional[int] = None,
) -> ResourceResult:
    """
    Get complete audit trail for an application.
    
    Resource: ledger://applications/{id}/audit-trail
    Source: Direct stream load (justified exception)
    SLO: p99 < 500ms
    
    This is a justified exception to the projection-only rule because:
    - Audit trails need the complete event stream
    - Temporal range queries require direct stream access
    """
    try:
        stream_id = f"loan-{application_id}"
        
        events = await store.load_stream(
            stream_id,
            from_position=from_position or 0,
            to_position=to_position,
        )
        
        return ResourceResult(
            success=True,
            data={
                "application_id": application_id,
                "stream_id": stream_id,
                "events": events,
                "event_count": len(events),
            }
        )
    except Exception as e:
        return ResourceResult(
            success=False,
            data={},
            error={"error_type": "QueryError", "message": str(e)}
        )


# ─── Agent Resources ─────────────────────────────────────────────────────────

async def get_agent_performance(
    projections,
    agent_id: str,
) -> ResourceResult:
    """
    Get agent performance metrics.
    
    Resource: ledger://agents/{id}/performance
    Source: AgentPerformanceLedger projection
    SLO: p99 < 50ms
    """
    try:
        perf_proj = projections.get("agent_performance")
        if not perf_proj:
            return ResourceResult(
                success=False,
                data={},
                error={"error_type": "ProjectionNotFound", "message": "agent_performance not available"}
            )
        
        metrics = perf_proj.get_by_agent(agent_id)
        
        if not metrics:
            return ResourceResult(
                success=False,
                data={},
                error={"error_type": "NotFound", "message": f"No performance data for agent {agent_id}"}
            )
        
        return ResourceResult(
            success=True,
            data={
                "agent_id": agent_id,
                "metrics": metrics,
            }
        )
    except Exception as e:
        return ResourceResult(
            success=False,
            data={},
            error={"error_type": "QueryError", "message": str(e)}
        )


async def get_agent_session(
    store,
    agent_id: str,
    session_id: str,
) -> ResourceResult:
    """
    Get agent session details.
    
    Resource: ledger://agents/{id}/sessions/{session_id}
    Source: Direct stream load
    SLO: p99 < 300ms
    """
    try:
        stream_id = f"agent-{agent_id}-{session_id}"
        
        events = await store.load_stream(stream_id)
        
        return ResourceResult(
            success=True,
            data={
                "agent_id": agent_id,
                "session_id": session_id,
                "stream_id": stream_id,
                "events": events,
                "event_count": len(events),
            }
        )
    except Exception as e:
        return ResourceResult(
            success=False,
            data={},
            error={"error_type": "QueryError", "message": str(e)}
        )


# ─── Health Resource ─────────────────────────────────────────────────────────

async def get_ledger_health(
    daemon,
) -> ResourceResult:
    """
    Get projection daemon lag metrics.
    
    Resource: ledger://ledger/health
    Source: ProjectionDaemon.get_all_lags()
    SLO: p99 < 10ms
    """
    try:
        lags = await daemon.get_all_lags()
        
        # Determine overall health
        all_healthy = all(lag < 1000 for lag in lags.values())  # < 1s lag = healthy
        
        return ResourceResult(
            success=True,
            data={
                "healthy": all_healthy,
                "projection_lags": lags,
            }
        )
    except Exception as e:
        return ResourceResult(
            success=False,
            data={},
            error={"error_type": "HealthCheckError", "message": str(e)}
        )
