"""
src/aggregates/agent_session.py
===============================
Agent Session Aggregate - Domain Logic Implementation

Implements:
- Gas Town pattern: AgentContextLoaded must be first event before any decisions
- Model version tracking
- Session state management

The Gas Town Persistent Ledger Pattern:
Every agent action is written to the event store as an event BEFORE the action is executed.
On restart, the agent replays its event stream to reconstruct its context window. 
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class AgentSessionState(str, Enum):
    """States for an agent session."""
    INITIALIZED = "INITIALIZED"
    CONTEXT_LOADED = "CONTEXT_LOADED"
    PROCESSING = "PROCESSING"
    AWAITING_INPUT = "AWAITING_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


VALID_SESSION_TRANSITIONS = {
    AgentSessionState.INITIALIZED: [AgentSessionState.CONTEXT_LOADED],
    AgentSessionState.CONTEXT_LOADED: [AgentSessionState.PROCESSING, AgentSessionState.AWAITING_INPUT],
    AgentSessionState.PROCESSING: [AgentSessionState.COMPLETED, AgentSessionState.FAILED, AgentSessionState.AWAITING_INPUT],
    AgentSessionState.AWAITING_INPUT: [AgentSessionState.PROCESSING, AgentSessionState.COMPLETED],
    AgentSessionState.COMPLETED: [],
    AgentSessionState.FAILED: [],
}


class AgentSessionDomainError(Exception):
    """Raised when an agent session business rule is violated."""
    pass


@dataclass
class AgentSessionAggregate:
    """
    Agent Session Aggregate Root.
    
    Manages the lifecycle of an AI agent's work session.
    Implements the Gas Town pattern: context must be loaded before decisions.
    """
    agent_id: str
    session_id: str
    agent_type: Optional[str] = None
    state: AgentSessionState = AgentSessionState.INITIALIZED
    
    # Context tracking (Gas Town pattern)
    context_loaded: bool = False
    context_source: Optional[str] = None
    context_token_count: int = 0
    model_version: Optional[str] = None
    
    # Execution tracking
    actions_completed: int = 0
    decisions_made: int = 0
    last_event_timestamp: Optional[datetime] = None
    
    # Version for optimistic concurrency
    version: int = 0

    @classmethod
    async def load(cls, store, agent_id: str, session_id: str) -> "AgentSessionAggregate":
        """
        Load and replay event stream to rebuild agent session state.
        """
        agg = cls(agent_id=agent_id, session_id=session_id)
        
        # Load events from the stream
        events = await store.load_stream(f"agent-{agent_id}-{session_id}")
        
        # Replay each event to rebuild state
        for event in events:
            agg.apply(event)
        
        return agg

    def apply(self, event: dict) -> None:
        """Apply one event to update aggregate state."""
        et = event.get("event_type")
        p = event.get("payload", {})
        
        self.version += 1
        self.last_event_timestamp = datetime.utcnow()
        
        if et == "AgentContextLoaded":
            self._on_context_loaded(p)
        elif et == "AgentNodeExecuted":
            self._on_node_executed(p)
        elif et == "AgentToolCalled":
            self._on_tool_called(p)
        elif et == "AgentOutputWritten":
            self._on_output_written(p)
        elif et == "AgentSessionCompleted":
            self._on_session_completed(p)
        elif et == "AgentSessionFailed":
            self._on_session_failed(p)

    def _on_context_loaded(self, payload: dict) -> None:
        """Handle AgentContextLoaded event - Gas Town pattern."""
        self.state = AgentSessionState.CONTEXT_LOADED
        self.context_loaded = True
        self.context_source = payload.get("context_source")
        self.context_token_count = payload.get("context_token_count", 0)
        self.model_version = payload.get("model_version")

    def _on_node_executed(self, payload: dict) -> None:
        """Handle AgentNodeExecuted event."""
        self.state = AgentSessionState.PROCESSING
        self.actions_completed += 1

    def _on_tool_called(self, payload: dict) -> None:
        """Handle AgentToolCalled event."""
        self.state = AgentSessionState.PROCESSING

    def _on_output_written(self, payload: dict) -> None:
        """Handle AgentOutputWritten event - marks a decision was made."""
        self.decisions_made += 1

    def _on_session_completed(self, payload: dict) -> None:
        """Handle AgentSessionCompleted event."""
        self.state = AgentSessionState.COMPLETED

    def _on_session_failed(self, payload: dict) -> None:
        """Handle AgentSessionFailed event."""
        self.state = AgentSessionState.FAILED

    # ─── BUSINESS RULES ───────────────────────────────────────────────────────

    def assert_context_loaded(self) -> None:
        """
        Gas Town Pattern: Assert that context has been loaded before any operations.
        
        This is critical - an agent cannot make decisions without first loading its context.
        """
        if not self.context_loaded:
            raise AgentSessionDomainError(
                f"Agent {self.agent_id} session {self.session_id} cannot operate "
                "without first loading context. Call start_agent_session first."
            )

    def assert_valid_transition(self, target: AgentSessionState) -> None:
        """Assert that a session state transition is valid."""
        allowed = VALID_SESSION_TRANSITIONS.get(self.state, [])
        if target not in allowed:
            raise AgentSessionDomainError(
                f"Invalid session state transition: {self.state.value} → {target.value}"
            )

    def assert_model_version_current(self, claimed_version: str) -> None:
        """Assert that the model version matches the current session."""
        if self.model_version and self.model_version != claimed_version:
            raise AgentSessionDomainError(
                f"Model version mismatch: session uses {self.model_version}, "
                f"but command specifies {claimed_version}"
            )

    # ─── COMMAND HANDLERS ─────────────────────────────────────────────────

    async def handle_start_session(
        self,
        store,
        agent_id: str,
        session_id: str,
        agent_type: str,
        model_version: str,
        context_source: str,
        context_token_count: int,
    ) -> list[dict]:
        """
        Handle start_agent_session command - Gas Town pattern entry point.
        
        This must be called before any agent decision can be made.
        """
        # Validate
        if self.version > 0:
            raise AgentSessionDomainError("Session already started")
        
        # Determine new events
        events = [{
            "event_type": "AgentContextLoaded",
            "event_version": 1,
            "payload": {
                "agent_id": agent_id,
                "session_id": session_id,
                "context_source": context_source,
                "context_token_count": context_token_count,
                "model_version": model_version,
            }
        }]
        
        # Append
        await store.append(
            f"agent-{agent_id}-{session_id}",
            events,
            expected_version=self.version,
        )
        
        return events

    async def handle_record_decision(
        self,
        store,
        agent_id: str,
        session_id: str,
        decision_data: dict,
    ) -> list[dict]:
        """
        Handle record_agent_decision command.
        
        Business rule: Context must be loaded first (Gas Town pattern).
        """
        # Validate
        self.assert_context_loaded()
        
        # Determine new events
        events = [{
            "event_type": "AgentOutputWritten",
            "event_version": 1,
            "payload": {
                "agent_id": agent_id,
                "session_id": session_id,
                "decision_data": decision_data,
            }
        }]
        
        # Append
        await store.append(
            f"agent-{agent_id}-{session_id}",
            events,
            expected_version=self.version,
        )
        
        return events
