"""
src/projections/application_summary.py
====================================
ApplicationSummary Projection

A read-optimised view of every loan application's current state.
This is the primary query model for the loan application domain.

Table Schema:
- application_id (PK)
- state
- applicant_id
- requested_amount_usd
- approved_amount_usd
- risk_tier
- fraud_score
- compliance_status
- decision
- agent_sessions_completed
- last_event_type
- last_event_at
- human_reviewer_id
- final_decision_at
"""
from datetime import datetime
from typing import Optional
from src.projections.daemon import Projection


class ApplicationSummaryProjection(Projection):
    """
    Projection for loan application state.
    
    Maintains a current-state view of all loan applications,
    updated asynchronously by the projection daemon.
    """
    
    def __init__(self):
        self._name = "application_summary"
        self._state: dict[str, dict] = {}
    
    @property
    def name(self) -> str:
        return self._name
    
    async def apply(self, event: dict) -> None:
        """Apply an event to update the application summary."""
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        application_id = payload.get("application_id")
        
        if not application_id:
            return
        
        # Initialize or get existing state
        if application_id not in self._state:
            self._state[application_id] = self._create_default(application_id)
        
        app_state = self._state[application_id]
        
        # Apply event-specific updates
        if event_type == "ApplicationSubmitted":
            app_state["state"] = "SUBMITTED"
            app_state["applicant_id"] = payload.get("applicant_id")
            app_state["requested_amount_usd"] = payload.get("requested_amount_usd")
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "CreditAnalysisRequested":
            app_state["state"] = "CREDIT_ANALYSIS_REQUESTED"
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "CreditAnalysisCompleted":
            app_state["state"] = "CREDIT_ANALYSIS_COMPLETE"
            app_state["risk_tier"] = payload.get("risk_tier")
            app_state["recommended_limit_usd"] = payload.get("recommended_limit_usd")
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "FraudScreeningCompleted":
            app_state["state"] = "FRAUD_SCREENING_COMPLETE"
            app_state["fraud_score"] = payload.get("fraud_score")
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "ComplianceCheckRequested":
            app_state["state"] = "COMPLIANCE_REVIEW"
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "ComplianceRulePassed":
            app_state["compliance_status"] = "PASSED"
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "ComplianceRuleFailed":
            app_state["compliance_status"] = "FAILED"
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "DecisionGenerated":
            app_state["state"] = "PENDING_DECISION"
            app_state["decision"] = payload.get("recommendation")
            app_state["confidence_score"] = payload.get("confidence_score")
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "HumanReviewCompleted":
            app_state["human_reviewer_id"] = payload.get("reviewer_id")
            app_state["override"] = payload.get("override", False)
            if payload.get("override"):
                app_state["decision"] = payload.get("final_decision")
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "ApplicationApproved":
            app_state["state"] = "FINAL_APPROVED"
            app_state["approved_amount_usd"] = payload.get("approved_amount_usd")
            app_state["interest_rate"] = payload.get("interest_rate")
            app_state["approved_by"] = payload.get("approved_by")
            app_state["final_decision_at"] = event.get("recorded_at")
            app_state["decision"] = "APPROVED"
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
            
        elif event_type == "ApplicationDeclined":
            app_state["state"] = "FINAL_DECLINED"
            app_state["decline_reasons"] = payload.get("decline_reasons", [])
            app_state["final_decision_at"] = event.get("recorded_at")
            app_state["decision"] = "DECLINED"
            app_state["last_event_type"] = event_type
            app_state["last_event_at"] = event.get("recorded_at")
    
    def _create_default(self, application_id: str) -> dict:
        """Create default application state."""
        return {
            "application_id": application_id,
            "state": "INITIAL",
            "applicant_id": None,
            "requested_amount_usd": None,
            "approved_amount_usd": None,
            "risk_tier": None,
            "fraud_score": None,
            "compliance_status": "PENDING",
            "decision": None,
            "confidence_score": None,
            "recommended_limit_usd": None,
            "agent_sessions_completed": [],
            "last_event_type": None,
            "last_event_at": None,
            "human_reviewer_id": None,
            "override": False,
            "final_decision_at": None,
            "interest_rate": None,
            "approved_by": None,
            "decline_reasons": [],
        }
    
    def get(self, application_id: str) -> Optional[dict]:
        """Get application summary by ID."""
        return self._state.get(application_id)
    
    def get_all(self) -> list[dict]:
        """Get all application summaries."""
        return list(self._state.values())
    
    def clear(self) -> None:
        """Clear all projection data (for rebuild)."""
        self._state = {}
