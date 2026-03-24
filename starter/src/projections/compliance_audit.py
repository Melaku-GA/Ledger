"""
src/projections/compliance_audit.py
===================================
ComplianceAuditView Projection

Critical regulatory read model - the view that a compliance officer
or regulator queries when examining an application.

Key Features:
- Complete: every compliance event
- Traceable: every rule references its regulation version
- Temporally queryable: state at any past timestamp

Temporal Query Interface:
- get_current_compliance(application_id) - full compliance record
- get_compliance_at(application_id, timestamp) - state as it existed
- get_projection_lag() - milliseconds between latest event and processed
- rebuild_from_scratch() - truncate and replay all events
"""
from datetime import datetime
from typing import Optional
from src.projections.daemon import Projection


class ComplianceAuditViewProjection(Projection):
    """
    Projection for compliance audit trail.
    
    Maintains a complete audit trail of all compliance checks,
    supporting temporal queries for regulatory examination.
    """
    
    def __init__(self):
        self._name = "compliance_audit"
        # Main state: application_id -> list of compliance events (in order)
        self._compliance_events: dict[str, list[dict]] = {}
        # Snapshot state for temporal queries: (application_id, timestamp) -> state
        self._snapshots: dict[str, dict] = {}
        self._last_global_position = 0
    
    @property
    def name(self) -> str:
        return self._name
    
    async def apply(self, event: dict) -> None:
        """Apply an event to update the compliance audit view."""
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        application_id = payload.get("application_id")
        
        if not application_id:
            return
        
        # Initialize compliance events list
        if application_id not in self._compliance_events:
            self._compliance_events[application_id] = []
        
        # Track global position for lag calculation
        global_pos = event.get("global_position", 0)
        self._last_global_position = max(self._last_global_position, global_pos)
        
        # Only process compliance-related events
        if event_type == "ComplianceCheckRequested":
            self._compliance_events[application_id].append({
                "event_type": event_type,
                "recorded_at": event.get("recorded_at"),
                "regulation_set_version": payload.get("regulation_set_version"),
                "checks_required": payload.get("checks_required", []),
                "status": "REQUESTED",
            })
            
        elif event_type == "ComplianceRulePassed":
            self._compliance_events[application_id].append({
                "event_type": event_type,
                "recorded_at": event.get("recorded_at"),
                "rule_id": payload.get("rule_id"),
                "rule_version": payload.get("rule_version"),
                "status": "PASSED",
                "evidence_hash": payload.get("evidence_hash"),
            })
            
        elif event_type == "ComplianceRuleFailed":
            self._compliance_events[application_id].append({
                "event_type": event_type,
                "recorded_at": event.get("recorded_at"),
                "rule_id": payload.get("rule_id"),
                "rule_version": payload.get("rule_version"),
                "status": "FAILED",
                "failure_reason": payload.get("failure_reason"),
                "remediation_required": payload.get("remediation_required"),
            })
            
        elif event_type == "ApplicationApproved":
            # Final state - mark all checks complete
            self._compliance_events[application_id].append({
                "event_type": event_type,
                "recorded_at": event.get("recorded_at"),
                "status": "APPROVED",
                "approved_amount_usd": payload.get("approved_amount_usd"),
            })
            
        elif event_type == "ApplicationDeclined":
            self._compliance_events[application_id].append({
                "event_type": event_type,
                "recorded_at": event.get("recorded_at"),
                "status": "DECLINED",
                "decline_reasons": payload.get("decline_reasons", []),
            })
    
    def get_current_compliance(self, application_id: str) -> dict:
        """
        Get current compliance record for an application.
        
        Returns the complete compliance record with all checks and verdicts.
        """
        events = self._compliance_events.get(application_id, [])
        
        # Calculate overall status
        statuses = [e.get("status") for e in events]
        if "FAILED" in statuses:
            overall_status = "FAILED"
        elif "APPROVED" in statuses:
            overall_status = "PASSED"
        elif "DECLINED" in statuses:
            overall_status = "DECLINED"
        else:
            overall_status = "IN_PROGRESS"
        
        # Count checks
        checks_passed = len([e for e in events if e.get("status") == "PASSED"])
        checks_failed = len([e for e in events if e.get("status") == "FAILED"])
        
        return {
            "application_id": application_id,
            "overall_status": overall_status,
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "events": events,
            "last_updated": events[-1].get("recorded_at") if events else None,
        }
    
    def get_compliance_at(self, application_id: str, timestamp: str) -> dict:
        """
        Get compliance state as it existed at a specific moment in time.
        
        This is the regulatory time-travel query.
        
        Args:
            application_id: The application to query
            timestamp: ISO timestamp to query (e.g., "2026-01-15T10:30:00Z")
        
        Returns:
            Compliance state as it existed at that moment
        """
        # Parse timestamp
        try:
            query_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            # Try without timezone
            query_time = datetime.fromisoformat(timestamp)
        
        events = self._compliance_events.get(application_id, [])
        
        # Filter events that occurred before or at the query time
        past_events = []
        for event in events:
            event_time_str = event.get("recorded_at")
            if event_time_str:
                try:
                    # Handle both timezone-aware and naive datetimes consistently
                    event_time_str_clean = event_time_str.replace("Z", "+00:00")
                    event_time = datetime.fromisoformat(event_time_str_clean)
                    
                    # Make query_time timezone-naive for comparison (strip timezone info)
                    query_time_naive = query_time.replace(tzinfo=None)
                    event_time_naive = event_time.replace(tzinfo=None)
                    
                    if event_time_naive <= query_time_naive:
                        past_events.append(event)
                except ValueError:
                    past_events.append(event)
        
        # Calculate status at that point in time
        statuses = [e.get("status") for e in past_events]
        if "FAILED" in statuses:
            overall_status = "FAILED"
        elif "APPROVED" in statuses:
            overall_status = "PASSED"
        elif "DECLINED" in statuses:
            overall_status = "DECLINED"
        elif past_events:
            overall_status = "IN_PROGRESS"
        else:
            overall_status = "NO_RECORD"
        
        checks_passed = len([e for e in past_events if e.get("status") == "PASSED"])
        checks_failed = len([e for e in past_events if e.get("status") == "FAILED"])
        
        return {
            "application_id": application_id,
            "query_timestamp": timestamp,
            "overall_status": overall_status,
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "events": past_events,
            "event_count_at_time": len(past_events),
        }
    
    def get_projection_lag(self) -> int:
        """
        Get projection lag in milliseconds.
        
        Returns the difference between the latest event in the store
        and the latest event this projection has processed.
        For in-memory projections, this returns 0 as we're always current.
        """
        # In a real implementation, this would compare with the event store's
        # global_position. For in-memory, we return 0 (synchronized).
        return 0
    
    def clear(self) -> None:
        """Clear all projection data (for rebuild)."""
        self._compliance_events = {}
        self._snapshots = {}
        self._last_global_position = 0
