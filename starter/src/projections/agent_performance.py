"""
src/projections/agent_performance.py
====================================
AgentPerformanceLedger Projection

Aggregated performance metrics per AI agent model version.
Enables the question: "Has agent v2.3 been making systematically 
different decisions than v2.2?"

Table Schema:
- agent_id
- model_version (composite key)
- analyses_completed
- decisions_generated
- avg_confidence_score
- avg_duration_ms
- approve_rate
- decline_rate
- refer_rate
- human_override_rate
- first_seen_at
- last_seen_at
"""
from datetime import datetime
from typing import Optional
from src.projections.daemon import Projection


class AgentPerformanceLedgerProjection(Projection):
    """
    Projection for agent performance metrics.
    
    Tracks aggregated performance metrics per agent and model version,
    enabling analysis of agent decision patterns over time.
    """
    
    def __init__(self):
        self._name = "agent_performance"
        self._state: dict[str, dict] = {}  # key: (agent_id, model_version)
    
    @property
    def name(self) -> str:
        return self._name
    
    def _make_key(self, agent_id: str, model_version: str) -> str:
        """Create composite key for agent+model version."""
        return f"{agent_id}:{model_version}"
    
    async def apply(self, event: dict) -> None:
        """Apply an event to update agent performance metrics."""
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        
        # Extract agent info from various event types
        agent_id = payload.get("agent_id") or payload.get("orchestrator_agent_id")
        model_version = payload.get("model_version")
        
        if not agent_id or not model_version:
            return
        
        key = self._make_key(agent_id, model_version)
        
        # Initialize state for this agent+version combination
        if key not in self._state:
            self._state[key] = self._create_default(agent_id, model_version)
        
        stats = self._state[key]
        
        # Update metrics based on event type
        if event_type == "AgentContextLoaded":
            stats["first_seen_at"] = event.get("recorded_at")
            stats["last_seen_at"] = event.get("recorded_at")
            
        elif event_type == "CreditAnalysisCompleted":
            stats["analyses_completed"] += 1
            
            # Track confidence scores
            confidence = payload.get("confidence_score")
            if confidence is not None:
                stats["_confidence_sum"] = stats.get("_confidence_sum", 0) + confidence
                stats["avg_confidence_score"] = stats["_confidence_sum"] / stats["analyses_completed"]
            
            # Track duration
            duration = payload.get("analysis_duration_ms")
            if duration:
                stats["_duration_sum"] = stats.get("_duration_sum", 0) + duration
                stats["avg_duration_ms"] = stats["_duration_sum"] / stats["analyses_completed"]
            
            stats["last_seen_at"] = event.get("recorded_at")
            
        elif event_type == "FraudScreeningCompleted":
            stats["analyses_completed"] += 1
            stats["last_seen_at"] = event.get("recorded_at")
            
        elif event_type == "DecisionGenerated":
            stats["decisions_generated"] += 1
            
            recommendation = payload.get("recommendation", "")
            if recommendation == "APPROVE":
                stats["approve_rate"] = stats.get("approve_rate", 0) + 1
            elif recommendation == "DECLINE":
                stats["decline_rate"] = stats.get("decline_rate", 0) + 1
            elif recommendation == "REFER":
                stats["refer_rate"] = stats.get("refer_rate", 0) + 1
            
            stats["last_seen_at"] = event.get("recorded_at")
            
        elif event_type == "HumanReviewCompleted":
            if payload.get("override", False):
                stats["human_override_rate"] = stats.get("human_override_rate", 0) + 1
    
    def _create_default(self, agent_id: str, model_version: str) -> dict:
        """Create default performance stats."""
        return {
            "agent_id": agent_id,
            "model_version": model_version,
            "analyses_completed": 0,
            "decisions_generated": 0,
            "avg_confidence_score": None,
            "avg_duration_ms": None,
            "approve_rate": 0,
            "decline_rate": 0,
            "refer_rate": 0,
            "human_override_rate": 0,
            "first_seen_at": None,
            "last_seen_at": None,
            # Internal tracking fields
            "_confidence_sum": 0,
            "_duration_sum": 0,
        }
    
    def get(self, agent_id: str, model_version: str) -> Optional[dict]:
        """Get performance metrics for a specific agent+version."""
        key = self._make_key(agent_id, model_version)
        result = self._state.get(key, {}).copy()
        # Remove internal tracking fields
        result.pop("_confidence_sum", None)
        result.pop("_duration_sum", None)
        return result if result.get("agent_id") else None
    
    def get_all(self) -> list[dict]:
        """Get all performance metrics."""
        results = []
        for key, stats in self._state.items():
            result = stats.copy()
            result.pop("_confidence_sum", None)
            result.pop("_duration_sum", None)
            results.append(result)
        return results
    
    def get_by_agent(self, agent_id: str) -> list[dict]:
        """Get all performance metrics for a specific agent (all versions)."""
        results = []
        for key, stats in self._state.items():
            if stats["agent_id"] == agent_id:
                result = stats.copy()
                result.pop("_confidence_sum", None)
                result.pop("_duration_sum", None)
                results.append(result)
        return results
    
    def clear(self) -> None:
        """Clear all projection data (for rebuild)."""
        self._state = {}
