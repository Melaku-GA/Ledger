"""
src/regulatory/package.py
=========================
Regulatory Examination Package Generator.

Generates a complete, self-contained examination package containing:
- The complete event stream for the application
- The state of every projection as it existed at examination_date
- The audit chain integrity verification result
- A human-readable narrative of the application lifecycle
- Model versions, confidence scores, and input data hashes
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import json
import hashlib


@dataclass
class RegulatoryPackage:
    """Complete regulatory examination package."""
    application_id: str
    examination_date: str
    generated_at: str
    package_version: str = "1.0"
    
    # Event stream data
    event_stream: list[dict] = field(default_factory=list)
    event_count: int = 0
    
    # Projection states
    application_summary: dict = field(default_factory=dict)
    compliance_audit: dict = field(default_factory=dict)
    agent_performance: list[dict] = field(default_factory=list)
    
    # Integrity verification
    integrity_check: dict = field(default_factory=dict)
    
    # Human-readable narrative
    narrative: str = ""
    narrative_events: list[dict] = field(default_factory=list)
    
    # Agent metadata
    agent_metadata: list[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "application_id": self.application_id,
            "examination_date": self.examination_date,
            "generated_at": self.generated_at,
            "package_version": self.package_version,
            "event_stream": self.event_stream,
            "event_count": self.event_count,
            "application_summary": self.application_summary,
            "compliance_audit": self.compliance_audit,
            "agent_performance": self.agent_performance,
            "integrity_check": self.integrity_check,
            "narrative": self.narrative,
            "narrative_events": self.narrative_events,
            "agent_metadata": self.agent_metadata,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


class RegulatoryPackageGenerator:
    """
    Generates regulatory examination packages.
    
    Produces self-contained JSON files that regulators can verify
    against the database independently.
    """
    
    def __init__(self, event_store, projections: dict = None):
        self.store = event_store
        self.projections = projections or {}
    
    async def generate_package(
        self,
        application_id: str,
        examination_date: str = None,
    ) -> RegulatoryPackage:
        """
        Generate a complete regulatory examination package.
        
        Args:
            application_id: The application to package
            examination_date: Date for temporal queries (defaults to now)
            
        Returns:
            Complete RegulatoryPackage ready for export
        """
        examination_date = examination_date or datetime.utcnow().isoformat()
        
        package = RegulatoryPackage(
            application_id=application_id,
            examination_date=examination_date,
            generated_at=datetime.utcnow().isoformat(),
        )
        
        # 1. Get complete event stream
        events = await self._get_event_stream(application_id)
        package.event_stream = events
        package.event_count = len(events)
        
        # 2. Get application summary projection
        if "application_summary" in self.projections:
            proj = self.projections["application_summary"]
            package.application_summary = await proj.get(application_id)
        
        # 3. Get compliance audit view (temporal)
        if "compliance_audit" in self.projections:
            proj = self.projections["compliance_audit"]
            # Get historical state at examination date
            package.compliance_audit = await proj.get_compliance_at(
                application_id, examination_date
            )
        
        # 4. Get agent performance data
        if "agent_performance" in self.projections:
            proj = self.projections["agent_performance"]
            package.agent_performance = await proj.get_all()
        
        # 5. Run integrity check
        package.integrity_check = await self._run_integrity_check(application_id)
        
        # 6. Generate human-readable narrative
        narrative_data = self._generate_narrative(events)
        package.narrative = narrative_data["narrative"]
        package.narrative_events = narrative_data["events"]
        
        # 7. Extract agent metadata
        package.agent_metadata = self._extract_agent_metadata(events)
        
        return package
    
    async def _get_event_stream(self, application_id: str) -> list[dict]:
        """Get all events for an application."""
        stream_id = f"loan-{application_id}"
        events = await self.store.load_stream(stream_id)
        
        # Also get agent session events (load_all returns an async generator)
        agent_events = []
        async for e in self.store.load_all():
            if e.get("payload", {}).get("application_id") == application_id:
                agent_events.append(e)
        
        # Combine and sort
        all_events = events + agent_events
        all_events.sort(key=lambda e: e.get("recorded_at", ""))
        
        return [self._serialize_event(e) for e in all_events]
    
    def _serialize_event(self, event: dict) -> dict:
        """Serialize event for JSON output."""
        return {
            "event_id": str(event.get("event_id", "")),
            "event_type": event.get("event_type", ""),
            "event_version": event.get("event_version", 1),
            "stream_id": event.get("stream_id", ""),
            "stream_position": event.get("stream_position", 0),
            "recorded_at": event.get("recorded_at", ""),
            "payload": event.get("payload", {}),
            "metadata": event.get("metadata", {}),
        }
    
    async def _run_integrity_check(self, application_id: str) -> dict:
        """Run integrity check on the audit chain."""
        from src.integrity.audit_chain import run_integrity_check
        
        try:
            result = await run_integrity_check(
                self.store,
                entity_type="loan",
                entity_id=application_id,
            )
            return {
                "chain_valid": result.get("chain_valid", False),
                "tamper_detected": result.get("tamper_detected", False),
                "events_verified": result.get("events_verified", 0),
                "last_check_timestamp": result.get("check_timestamp", ""),
                "integrity_hash": result.get("integrity_hash", ""),
            }
        except Exception as e:
            return {
                "chain_valid": False,
                "error": str(e),
            }
    
    def _generate_narrative(self, events: list[dict]) -> dict:
        """Generate a human-readable narrative of the application lifecycle."""
        narrative_parts = []
        event_summaries = []
        
        for event in events:
            event_type = event.get("event_type", "")
            payload = event.get("payload", {})
            
            summary = {
                "event_type": event_type,
                "timestamp": event.get("recorded_at", ""),
                "description": "",
            }
            
            if event_type == "ApplicationSubmitted":
                applicant = payload.get("applicant_id", "Unknown")
                amount = payload.get("requested_amount_usd", 0)
                summary["description"] = f"Application submitted by {applicant} for ${amount:,}"
                narrative_parts.append(
                    f"Application submitted by {applicant} requesting ${amount:,} for {payload.get('loan_purpose', 'unspecified purposes')}."
                )
            
            elif event_type == "CreditAnalysisCompleted":
                risk = payload.get("risk_tier", "UNKNOWN")
                conf = payload.get("confidence_score", 0)
                summary["description"] = f"Credit analysis: risk={risk}, confidence={conf}"
                narrative_parts.append(
                    f"Credit analysis completed with {risk} risk assessment (confidence: {conf:.0%})."
                )
            
            elif event_type == "FraudScreeningCompleted":
                score = payload.get("fraud_score", 0)
                flags = payload.get("anomaly_flags", [])
                summary["description"] = f"Fraud score: {score}, flags: {flags}"
                narrative_parts.append(
                    f"Fraud screening completed with score {score:.1%}."
                )
            
            elif event_type == "ComplianceRulePassed":
                rule = payload.get("rule_id", "Unknown")
                summary["description"] = f"Compliance check passed: {rule}"
                narrative_parts.append(
                    f"Compliance check {rule} passed."
                )
            
            elif event_type == "ComplianceRuleFailed":
                rule = payload.get("rule_id", "Unknown")
                reason = payload.get("failure_reason", "Unknown")
                summary["description"] = f"Compliance check failed: {rule}"
                narrative_parts.append(
                    f"Compliance check {rule} failed: {reason}."
                )
            
            elif event_type == "DecisionGenerated":
                rec = payload.get("recommendation", "UNKNOWN")
                conf = payload.get("confidence_score", 0)
                summary["description"] = f"Decision: {rec}, confidence={conf}"
                narrative_parts.append(
                    f"Automated decision generated: {rec} (confidence: {conf:.0%})."
                )
            
            elif event_type == "HumanReviewCompleted":
                decision = payload.get("final_decision", "UNKNOWN")
                override = payload.get("override", False)
                summary["description"] = f"Human review: {decision}, override={override}"
                if override:
                    narrative_parts.append(
                        f"Human reviewer {payload.get('reviewer_id')} overrode the automated decision to {decision}."
                    )
                else:
                    narrative_parts.append(
                        f"Human reviewer {payload.get('reviewer_id')} confirmed the automated decision."
                    )
            
            elif event_type == "ApplicationApproved":
                amount = payload.get("approved_amount_usd", 0)
                rate = payload.get("interest_rate", "N/A")
                summary["description"] = f"Approved: ${amount:,} at {rate}%"
                narrative_parts.append(
                    f"Application approved for ${amount:,} at {rate}% interest."
                )
            
            elif event_type == "ApplicationDeclined":
                reasons = payload.get("decline_reasons", [])
                summary["description"] = f"Declined: {reasons}"
                narrative_parts.append(
                    f"Application declined. Reasons: {', '.join(reasons)}."
                )
            
            elif event_type == "AgentContextLoaded":
                agent_id = payload.get("agent_id", "Unknown")
                model = payload.get("model_version", "Unknown")
                summary["description"] = f"Agent {agent_id} loaded context (model: {model})"
                narrative_parts.append(
                    f"Agent {agent_id} loaded context using model {model}."
                )
            
            if summary["description"]:
                event_summaries.append(summary)
        
        # Join narrative with proper capitalization
        narrative = " ".join(narrative_parts)
        if narrative:
            narrative = narrative[0].upper() + narrative[1:]
        
        return {
            "narrative": narrative,
            "events": event_summaries,
        }
    
    def _extract_agent_metadata(self, events: list[dict]) -> list[dict]:
        """Extract agent model versions, confidence scores, and input hashes."""
        metadata = []
        
        for event in events:
            event_type = event.get("event_type", "")
            payload = event.get("payload", {})
            
            if event_type == "AgentContextLoaded":
                metadata.append({
                    "type": "session_start",
                    "agent_id": payload.get("agent_id"),
                    "session_id": payload.get("session_id"),
                    "model_version": payload.get("model_version"),
                    "context_source": payload.get("context_source"),
                    "timestamp": event.get("recorded_at", ""),
                })
            
            elif event_type == "CreditAnalysisCompleted":
                metadata.append({
                    "type": "credit_analysis",
                    "agent_id": payload.get("agent_id"),
                    "model_version": payload.get("model_version"),
                    "confidence_score": payload.get("confidence_score"),
                    "risk_tier": payload.get("risk_tier"),
                    "input_data_hash": payload.get("input_data_hash"),
                    "timestamp": event.get("recorded_at", ""),
                })
            
            elif event_type == "FraudScreeningCompleted":
                metadata.append({
                    "type": "fraud_screening",
                    "agent_id": payload.get("agent_id"),
                    "model_version": payload.get("screening_model_version"),
                    "fraud_score": payload.get("fraud_score"),
                    "input_data_hash": payload.get("input_data_hash"),
                    "timestamp": event.get("recorded_at", ""),
                })
            
            elif event_type == "DecisionGenerated":
                model_versions = payload.get("model_versions", {})
                metadata.append({
                    "type": "decision",
                    "orchestrator_id": payload.get("orchestrator_agent_id"),
                    "recommendation": payload.get("recommendation"),
                    "confidence_score": payload.get("confidence_score"),
                    "model_versions": model_versions,
                    "timestamp": event.get("recorded_at", ""),
                })
        
        return metadata


# ─── Convenience Function ─────────────────────────────────────────────────

async def generate_regulatory_package(
    store,
    application_id: str,
    examination_date: str = None,
    projections: dict = None,
) -> RegulatoryPackage:
    """
    Generate a complete regulatory examination package.
    
    Args:
        store: Event store instance
        application_id: Application ID to package
        examination_date: Historical date for temporal queries
        projections: Dict of projection name -> projection instance
        
    Returns:
        RegulatoryPackage that can be exported to JSON
        
    Example:
        package = await generate_regulatory_package(
            store, 
            "COMP-001",
            examination_date="2026-03-15T10:00:00Z"
        )
        print(package.to_json())
    """
    generator = RegulatoryPackageGenerator(store, projections)
    return await generator.generate_package(application_id, examination_date)
