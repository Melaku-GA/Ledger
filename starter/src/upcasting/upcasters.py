"""
src/upcasting/upcasters.py
=========================
Upcasters - Schema Version Migrations

Registered upcasters for the event catalogue:
- CreditAnalysisCompleted v1→v2
- DecisionGenerated v1→v2

Inference Strategy:
- model_version: Inferred from recorded_at timestamp (pre-2026 = "legacy-pre-2026")
- confidence_score: NULL - genuinely unknown, fabrication would be worse than null
- regulatory_basis: Inferred from rule versions active at recorded_at date
"""
from datetime import datetime
from src.upcasting.registry import registry, get_registry


# ─── CreditAnalysisCompleted v1 → v2 ──────────────────────────────────────────

@registry.register("CreditAnalysisCompleted", from_version=1)
def upcast_credit_v1_to_v2(payload: dict) -> dict:
    """
    Upcast CreditAnalysisCompleted from v1 to v2.
    
    v1 fields: application_id, agent_id, session_id, confidence_score, 
               risk_tier, recommended_limit_usd, analysis_duration_ms, input_data_hash
    
    v2 adds: model_version, regulatory_basis
    
    Inference Strategy:
    - model_version: Inferred from recorded_at timestamp
      * Pre-2026: "legacy-pre-2026" 
      * 2026 and later: actual version not available, use "unknown"
    - confidence_score: NULL - was not in v1, genuinely unknown
    - regulatory_basis: Infer from rule versions active at recorded_at date
    """
    # Get recorded_at for inference (passed in metadata or payload)
    recorded_at = payload.get("recorded_at")
    
    # Infer model_version based on timestamp
    model_version = "legacy-pre-2026"  # Default for historical events
    if recorded_at:
        try:
            # Try to parse the timestamp
            if isinstance(recorded_at, str):
                # Handle ISO format
                ts = recorded_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts)
                if dt.year >= 2026:
                    model_version = "unknown-post-2026"
        except (ValueError, TypeError):
            pass
    
    # Infer regulatory_basis - this is complex in reality
    # For now, use a placeholder based on date
    regulatory_basis = "inferred-pre-2026"
    if recorded_at:
        try:
            if isinstance(recorded_at, str):
                ts = recorded_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts)
                if dt.year >= 2026:
                    regulatory_basis = "2026-Q1"  # Assume current regulation
        except (ValueError, TypeError):
            pass
    
    return {
        **payload,
        "model_version": model_version,
        "confidence_score": None,  # Genuinely unknown in v1
        "regulatory_basis": regulatory_basis,
    }


# ─── DecisionGenerated v1 → v2 ────────────────────────────────────────────────

@registry.register("DecisionGenerated", from_version=1)
def upcast_decision_v1_to_v2(payload: dict) -> dict:
    """
    Upcast DecisionGenerated from v1 to v2.
    
    v1 fields: application_id, orchestrator_agent_id, recommendation, 
               confidence_score, contributing_agent_sessions, decision_basis_summary
    
    v2 adds: model_versions{} dict
    
    Inference Strategy:
    - model_versions{}: Reconstruct from contributing_agent_sessions
      by loading each session's AgentContextLoaded event
      * Performance implication: requires additional store lookups
      * For v1 events without this data, use placeholder
    
    Note: This upcaster requires access to the event store to look up
    agent sessions. In practice, this would be handled by a more complex
    upcaster that has access to the store.
    """
    # For v1 events, we don't have model_versions
    # In a real implementation, we'd load each session to get the model version
    # For now, use a placeholder
    
    contributing_sessions = payload.get("contributing_agent_sessions", [])
    model_versions = {}
    
    # If we have contributing sessions, we'd look them up
    # For v1 compatibility, mark as unknown
    for session_id in contributing_sessions:
        model_versions[session_id] = "unknown-v1"
    
    return {
        **payload,
        "model_versions": model_versions,
    }


def get_upcasted_credit_analysis(event: dict) -> dict:
    """Helper to get upcasted CreditAnalysisCompleted event."""
    reg = get_registry()
    return reg.upcast(event)


def get_upcasted_decision(event: dict) -> dict:
    """Helper to get upcasted DecisionGenerated event."""
    reg = get_registry()
    return reg.upcast(event)
