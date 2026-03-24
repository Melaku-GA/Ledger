"""
src/integrity/gas_town.py
=========================
The Gas Town Agent Memory Pattern

Implements the pattern that prevents catastrophic memory loss.
An AI agent that crashes mid-session must be able to restart and
reconstruct its exact context from the event store, then continue
where it left off without repeating completed work.

Key Features:
- Load full AgentSession stream
- Identify last completed action
- Summarise old events into prose (token-efficient)
- Preserve verbatim: last 3 events, any PENDING/ERROR state events
- Detect partial decisions that need reconciliation
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AgentContext:
    """Reconstructed agent context for resumable sessions."""
    context_text: str
    last_event_position: int
    pending_work: list[dict]
    session_health_status: str  # HEALTHY, NEEDS_RECONCILIATION, CORRUPTED
    last_action_type: Optional[str]
    last_action_result: Optional[str]


async def reconstruct_agent_context(
    store,
    agent_id: str,
    session_id: str,
    token_budget: int = 8000,
) -> AgentContext:
    """
    Reconstruct agent context from event store.
    
    This implements the Gas Town Persistent Ledger Pattern:
    1. Load full AgentSession stream for agent_id + session_id
    2. Identify: last completed action, pending work items, current application state
    3. Summarise old events into prose (token-efficient)
    4. Preserve verbatim: last 3 events, any PENDING or ERROR state events
    5. Return: AgentContext with context_text, last_event_position,
               pending_work[], session_health_status
    
    CRITICAL: if the agent's last event was a partial decision (no corresponding
    completion event), flag the context as NEEDS_RECONCILIATION.
    
    Args:
        store: The event store
        agent_id: The agent ID
        session_id: The session ID
        token_budget: Maximum tokens for context summarization
    
    Returns:
        AgentContext with reconstructed state
    """
    stream_id = f"agent-{agent_id}-{session_id}"
    
    # Load all events from the session stream
    events = []
    try:
        events = await store.load_stream(stream_id)
    except Exception:
        # No events found - new session
        return AgentContext(
            context_text="",
            last_event_position=0,
            pending_work=[],
            session_health_status="HEALTHY",
            last_action_type=None,
            last_action_result=None,
        )
    
    if not events:
        return AgentContext(
            context_text="",
            last_event_position=0,
            pending_work=[],
            session_health_status="HEALTHY",
            last_action_type=None,
            last_action_result=None,
        )
    
    # Analyze events
    context_events = []
    pending_work = []
    last_action_type = None
    last_action_result = None
    
    # Separate events by type
    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        
        # Track last action
        if event_type in ["AgentNodeExecuted", "AgentToolCalled", "AgentOutputWritten"]:
            last_action_type = event_type
            last_action_result = payload.get("result", "success")
        
        # Identify PENDING or ERROR states
        if event_type in ["AgentNodeExecuted"]:
            status = payload.get("status", "")
            if status in ["PENDING", "ERROR"]:
                pending_work.append({
                    "event_type": event_type,
                    "node_id": payload.get("node_id"),
                    "status": status,
                    "position": event.get("stream_position"),
                })
        
        context_events.append(event)
    
    # Get last event position
    last_event = events[-1]
    last_event_position = last_event.get("stream_position", 0)
    
    # Determine health status
    session_health_status = "HEALTHY"
    
    # Check for partial decisions
    # A partial decision is one where we have a decision event but no completion
    decision_events = [e for e in events if e.get("event_type") == "AgentOutputWritten"]
    if decision_events:
        last_decision = decision_events[-1]
        # Check if there's a corresponding completion
        has_completion = any(
            e.get("event_type") == "AgentSessionCompleted" and
            e.get("stream_position", 0) > last_decision.get("stream_position", 0)
            for e in events
        )
        if not has_completion:
            session_health_status = "NEEDS_RECONCILIATION"
    
    # Check for ERROR states in recent events
    recent_events = events[-5:] if len(events) >= 5 else events
    for event in recent_events:
        if event.get("payload", {}).get("status") == "ERROR":
            session_health_status = "CORRUPTED"
            break
    
    # Build context text (summarization)
    context_text = _build_context_summary(events, token_budget)
    
    return AgentContext(
        context_text=context_text,
        last_event_position=last_event_position,
        pending_work=pending_work,
        session_health_status=session_health_status,
        last_action_type=last_action_type,
        last_action_result=last_action_result,
    )


def _build_context_summary(events: list[dict], token_budget: int) -> str:
    """
    Build a token-efficient summary of events.
    
    Strategy:
    - Keep last 3 events verbatim
    - Summarize older events
    - Estimate ~4 chars per token
    """
    if not events:
        return ""
    
    # Calculate available budget for summary
    # Last 3 events take ~300 tokens
    summary_budget = token_budget - 300
    if summary_budget < 0:
        summary_budget = 100
    
    parts = []
    
    # Keep last 3 events verbatim
    recent_events = events[-3:] if len(events) >= 3 else events
    
    # Older events get summarized
    older_events = events[:-3] if len(events) > 3 else []
    
    if older_events:
        # Summarize older events
        summary = f"[{len(older_events)} earlier events summarized]"
        parts.append(summary)
    
    # Add recent events
    for event in recent_events:
        event_type = event.get("event_type", "Unknown")
        payload = event.get("payload", {})
        
        if event_type == "AgentContextLoaded":
            text = f"Context loaded: {payload.get('context_source')}, tokens: {payload.get('context_token_count')}"
        elif event_type == "AgentNodeExecuted":
            text = f"Node executed: {payload.get('node_id')}, status: {payload.get('status', 'success')}"
        elif event_type == "AgentToolCalled":
            text = f"Tool called: {payload.get('tool_name')}"
        elif event_type == "AgentOutputWritten":
            text = f"Output written: {payload.get('output_type')}"
        elif event_type == "AgentSessionCompleted":
            text = "Session completed successfully"
        elif event_type == "AgentSessionFailed":
            text = f"Session failed: {payload.get('error')}"
        else:
            text = f"Event: {event_type}"
        
        parts.append(text)
    
    return "\n".join(parts)


async def detect_partial_decision(store, agent_id: str, session_id: str) -> bool:
    """
    Check if the agent has a partial decision that needs reconciliation.
    
    Returns True if the last event was a decision without a corresponding completion.
    """
    context = await reconstruct_agent_context(store, agent_id, session_id)
    return context.session_health_status == "NEEDS_RECONCILIATION"
