"""
src/what_if/projector.py
========================
What-If Projector for counterfactual analysis.

Allows running counterfactual scenarios: "What would the decision have been
if the credit analysis had returned risk_tier='HIGH' instead of 'MEDIUM'?"

This implements the regulatory time-travel capability.
"""
from dataclasses import dataclass, field
from typing import Any
import hashlib
import json


@dataclass
class WhatIfResult:
    """Result of a what-if counterfactual analysis."""
    application_id: str
    real_outcome: dict
    counterfactual_outcome: dict
    divergence_events: list[dict] = field(default_factory=list)
    branch_point_event: str = ""
    analysis_timestamp: str = ""


class WhatIfProjector:
    """
    Projects application state under counterfactual scenarios.
    
    Key principles:
    - Never writes counterfactual events to the real store
    - Filters causally dependent events (skip events whose causation_id traces back to branch point)
    - Replays events with injected counterfactual events
    """
    
    def __init__(self, event_store):
        self.store = event_store
    
    async def run_what_if(
        self,
        application_id: str,
        branch_at_event_type: str,
        counterfactual_events: list[dict],
        projections: list[Any] = None,
    ) -> WhatIfResult:
        """
        Run a what-if counterfactual analysis.
        
        Args:
            application_id: The application to analyze
            branch_at_event_type: Event type to branch at (e.g., "CreditAnalysisCompleted")
            counterfactual_events: Events to inject instead of real ones
            projections: List of projections to evaluate under the scenario
            
        Returns:
            WhatIfResult with real and counterfactual outcomes
        """
        stream_id = f"loan-{application_id}"
        
        # 1. Load all events for the application stream
        all_events = await self.store.load_stream(stream_id)
        
        if not all_events:
            return WhatIfResult(
                application_id=application_id,
                real_outcome={"error": "No events found"},
                counterfactual_outcome={"error": "No events found"},
            )
        
        # 2. Find the branch point
        branch_index = -1
        for i, event in enumerate(all_events):
            if event["event_type"] == branch_at_event_type:
                branch_index = i
                break
        
        if branch_index == -1:
            return WhatIfResult(
                application_id=application_id,
                real_outcome={"error": f"Branch point event {branch_at_event_type} not found"},
                counterfactual_outcome={"error": f"Branch point event {branch_at_event_type} not found"},
            )
        
        branch_event = all_events[branch_index]
        
        # 3. Build pre-branch events (real)
        pre_branch_events = all_events[:branch_index]
        
        # 4. Build post-branch events, filtering causally dependent ones
        post_branch_events = []
        for event in all_events[branch_index + 1:]:
            # Check if this event is causally dependent on the branch
            if self._is_causally_dependent(event, branch_index, all_events):
                # Skip this event - it's dependent on the branch
                post_branch_events.append({
                    "event_type": event["event_type"],
                    "skipped": True,
                    "reason": "causally_dependent_on_branch",
                    "original": event,
                })
            else:
                # Keep this event - it's independent
                post_branch_events.append({
                    "event_type": event["event_type"],
                    "skipped": False,
                    "original": event,
                })
        
        # 5. Build the counterfactual event stream
        # Pre-branch real + counterfactual + post-branch independent
        counterfactual_stream = (
            pre_branch_events +
            counterfactual_events +
            [e["original"] for e in post_branch_events if not e.get("skipped", False)]
        )
        
        # 6. Compute real outcome (baseline)
        real_outcome = self._compute_outcome(all_events)
        
        # 7. Compute counterfactual outcome
        counterfactual_outcome = self._compute_outcome(counterfactual_stream)
        
        # 8. Find divergence events
        divergence_events = self._find_divergences(
            all_events, 
            counterfactual_stream,
            branch_index
        )
        
        return WhatIfResult(
            application_id=application_id,
            real_outcome=real_outcome,
            counterfactual_outcome=counterfactual_outcome,
            divergence_events=divergence_events,
            branch_point_event=branch_event["event_type"],
            analysis_timestamp=branch_event.get("recorded_at", ""),
        )
    
    def _is_causally_dependent(
        self, 
        event: dict, 
        branch_index: int, 
        all_events: list[dict]
    ) -> bool:
        """
        Check if an event is causally dependent on the branch point.
        
        An event is dependent if its causation_id traces back to an event
        at or after the branch point.
        """
        causation_id = event.get("metadata", {}).get("causation_id")
        
        if not causation_id:
            # No causation_id - check if it's after branch point in stream
            return True
        
        # Find the event that caused this one
        for i, e in enumerate(all_events):
            if e.get("event_id") == causation_id or e.get("metadata", {}).get("correlation_id") == causation_id:
                # If the causing event is at or after the branch, it's dependent
                return i >= branch_index
        
        # Default: treat as dependent if no clear lineage
        return True
    
    def _compute_outcome(self, events: list[dict]) -> dict:
        """Compute the outcome (final state) from an event stream."""
        outcome = {
            "state": None,
            "decision": None,
            "approved_amount": None,
            "risk_tier": None,
            "event_count": len(events),
        }
        
        for event in events:
            event_type = event.get("event_type", "")
            payload = event.get("payload", {})
            
            if event_type == "ApplicationSubmitted":
                outcome["state"] = "SUBMITTED"
                outcome["applicant"] = payload.get("applicant_id")
                outcome["requested_amount"] = payload.get("requested_amount_usd")
            
            elif event_type == "CreditAnalysisCompleted":
                outcome["risk_tier"] = payload.get("risk_tier")
                outcome["confidence"] = payload.get("confidence_score")
                outcome["state"] = "CREDIT_ANALYSIS_COMPLETE"
            
            elif event_type == "FraudScreeningCompleted":
                outcome["fraud_score"] = payload.get("fraud_score")
                outcome["state"] = "FRAUD_SCREENING_COMPLETE"
            
            elif event_type == "DecisionGenerated":
                outcome["decision"] = payload.get("recommendation")
                outcome["state"] = "PENDING_DECISION"
            
            elif event_type == "ApplicationApproved":
                outcome["state"] = "APPROVED"
                outcome["approved_amount"] = payload.get("approved_amount_usd")
                outcome["decision"] = "APPROVED"
            
            elif event_type == "ApplicationDeclined":
                outcome["state"] = "DECLINED"
                outcome["decision"] = "DECLINED"
        
        return outcome
    
    def _find_divergences(
        self, 
        real_events: list[dict], 
        counterfactual_events: list[dict],
        branch_index: int,
    ) -> list[dict]:
        """Find events that differ between real and counterfactual streams."""
        divergences = []
        
        for i, (real, cf) in enumerate(zip(real_events, counterfactual_events)):
            if real.get("event_type") != cf.get("event_type"):
                divergences.append({
                    "position": i,
                    "real_event": real.get("event_type"),
                    "counterfactual_event": cf.get("event_type"),
                    "reason": "event_type_mismatch",
                })
            elif real.get("payload") != cf.get("payload"):
                divergences.append({
                    "position": i,
                    "event_type": real.get("event_type"),
                    "reason": "payload_differs",
                    "real_payload": real.get("payload"),
                    "cf_payload": cf.get("payload"),
                })
        
        return divergences


# ─── Convenience Functions ────────────────────────────────────────────────

async def run_what_if(
    store,
    application_id: str,
    branch_at_event_type: str,
    counterfactual_events: list[dict],
    projections: list[Any] = None,
) -> WhatIfResult:
    """
    Convenience function to run what-if analysis.
    
    Example:
        # What if credit analysis returned HIGH risk instead of LOW?
        result = await run_what_if(
            store,
            "APP-001",
            "CreditAnalysisCompleted",
            [{
                "event_type": "CreditAnalysisCompleted",
                "event_version": 2,
                "payload": {
                    "application_id": "APP-001",
                    "risk_tier": "HIGH",  # Counterfactual!
                    "confidence_score": 0.3,
                    ...
                }
            }]
        )
    """
    projector = WhatIfProjector(store)
    return await projector.run_what_if(
        application_id=application_id,
        branch_at_event_type=branch_at_event_type,
        counterfactual_events=counterfactual_events,
        projections=projections,
    )
