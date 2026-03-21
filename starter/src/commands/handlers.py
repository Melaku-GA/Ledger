"""
src/commands/handlers.py
=======================
Command Handlers for The Ledger

Implements the command handler pattern:
1. Load current aggregate state from event store
2. Validate business rules
3. Determine new events to append
4. Append atomically with optimistic concurrency

This is the core of the domain logic layer.
"""
from typing import Optional
from datetime import datetime


async def handle_submit_application(
    store, 
    application_id: str, 
    correlation_id: str | None = None,
    causation_id: str | None = None,
    **application_data
) -> dict:
    """
    Handle Submit Application command.
    
    Pattern: Load → Validate → Determine → Append
    """
    from src.aggregates.loan_application import LoanApplicationAggregate
    
    # 1. Load current state (or create new)
    try:
        agg = await LoanApplicationAggregate.load(store, application_id)
    except Exception:
        agg = LoanApplicationAggregate(application_id=application_id)
    
    # 2. Validate business rules
    agg.assert_can_submit_application()
    
    # 3. Determine new events
    event = {
        "event_type": "ApplicationSubmitted",
        "event_version": 1,
        "payload": {
            "application_id": application_id,
            **application_data,
        }
    }
    
    # Generate unique causation_id if not provided
    if causation_id is None:
        causation_id = f"submit-{application_id}"
    
    # 4. Append to store with correlation and causation tracking
    await store.append(
        f"loan-{application_id}",
        [event],
        expected_version=agg.version,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    
    return {"status": "submitted", "application_id": application_id}


async def handle_credit_analysis_completed(
    store,
    application_id: str,
    agent_id: str,
    session_id: str,
    model_version: str,
    confidence_score: float,
    risk_tier: str,
    recommended_limit_usd: float,
    input_data: dict,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict:
    """
    Handle Credit Analysis Completed command.
    
    Business Rules:
    - Context must be loaded (Gas Town pattern via agent session)
    - Confidence floor: confidence < 0.6 → referral
    - Loads both loan and agent session aggregates for validation
    """
    from src.aggregates.loan_application import LoanApplicationAggregate
    from src.aggregates.agent_session import AgentSessionAggregate
    
    # 1. Load BOTH aggregates - loan application AND agent session
    loan_agg = await LoanApplicationAggregate.load(store, application_id)
    agent_agg = await AgentSessionAggregate.load(store, agent_id, session_id)
    
    # 2. Validate business rules on BOTH aggregates
    # Loan application state must allow credit analysis completion
    loan_agg.assert_can_complete_credit_analysis()
    
    # Agent session must have context loaded (Gas Town pattern enforcement)
    agent_agg.assert_context_loaded()
    
    # Agent session must be using current model version
    agent_agg.assert_model_version_current(model_version)
    
    # 3. Apply confidence floor rule
    if confidence_score < 0.6:
        # Would force referral in decision
        pass
    
    # Generate unique causation_id if not provided
    if causation_id is None:
        causation_id = f"credit-analysis-{application_id}-{session_id}"
    
    # Determine new events
    event = {
        "event_type": "CreditAnalysisCompleted",
        "event_version": 2,
        "payload": {
            "application_id": application_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "model_version": model_version,
            "confidence_score": confidence_score,
            "risk_tier": risk_tier,
            "recommended_limit_usd": recommended_limit_usd,
            "input_data_hash": str(hash(str(input_data))),
        }
    }
    
    # 4. Append to store with OCC, passing correlation_id and causation_id
    await store.append(
        f"loan-{application_id}",
        [event],
        expected_version=loan_agg.version,
        correlation_id=correlation_id or session_id,
        causation_id=causation_id,
    )
    
    return {
        "status": "completed",
        "application_id": application_id,
        "confidence_score": confidence_score,
    }


async def handle_generate_decision(
    store,
    application_id: str,
    orchestrator_agent_id: str,
    confidence_score: float,
    recommendation: str,
    contributing_sessions: list[str],
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict:
    """
    Handle Generate Decision command.
    
    Business Rules:
    - All required analyses must be complete
    - Confidence floor: confidence < 0.6 → referral
    - Causal chain: contributing sessions must be valid
    """
    from src.aggregates.loan_application import LoanApplicationAggregate
    
    # 1. Load current state
    agg = await LoanApplicationAggregate.load(store, application_id)
    
    # 2. Validate
    agg.assert_can_generate_decision()
    
    # Apply confidence floor rule
    if confidence_score < 0.6:
        recommendation = "REFER"
    
    # Generate unique causation_id if not provided
    if causation_id is None:
        causation_id = f"decision-{application_id}"
    
    # Determine new events
    event = {
        "event_type": "DecisionGenerated",
        "event_version": 2,
        "payload": {
            "application_id": application_id,
            "orchestrator_agent_id": orchestrator_agent_id,
            "recommendation": recommendation,
            "confidence_score": confidence_score,
            "contributing_agent_sessions": contributing_sessions,
            "decision_basis_summary": f"Based on credit analysis (confidence: {confidence_score})",
        }
    }
    
    # 4. Append with causal chain tracking
    await store.append(
        f"loan-{application_id}",
        [event],
        expected_version=agg.version,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    
    return {
        "status": "decision_generated",
        "application_id": application_id,
        "recommendation": recommendation,
    }


async def handle_human_review(
    store,
    application_id: str,
    reviewer_id: str,
    override: bool,
    final_decision: str,
    override_reason: Optional[str] = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict:
    """
    Handle Human Review Completed command.
    """
    from src.aggregates.loan_application import LoanApplicationAggregate
    
    # 1. Load current state
    agg = await LoanApplicationAggregate.load(store, application_id)
    
    # 2. Validate
    if override and not override_reason:
        raise ValueError("Override requires override_reason")
    
    # Generate unique causation_id if not provided
    if causation_id is None:
        causation_id = f"human-review-{application_id}"
    
    # Determine new events
    event = {
        "event_type": "HumanReviewCompleted",
        "event_version": 1,
        "payload": {
            "application_id": application_id,
            "reviewer_id": reviewer_id,
            "override": override,
            "final_decision": final_decision,
            "override_reason": override_reason,
        }
    }
    
    # 4. Append with causal chain tracking
    await store.append(
        f"loan-{application_id}",
        [event],
        expected_version=agg.version,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    
    return {
        "status": "review_completed",
        "application_id": application_id,
        "final_decision": final_decision,
    }


async def handle_final_approval(
    store,
    application_id: str,
    approved_amount_usd: float,
    interest_rate: float,
    approved_by: str,
    effective_date: str,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict:
    """
    Handle Final Approval command.
    
    Business Rule: Compliance checks must have passed
    """
    from src.aggregates.loan_application import LoanApplicationAggregate
    
    # 1. Load current state
    agg = await LoanApplicationAggregate.load(store, application_id)
    
    # 2. Validate compliance
    agg.assert_can_approve()
    
    # Generate unique causation_id if not provided
    if causation_id is None:
        causation_id = f"approval-{application_id}"
    
    # Determine new events
    event = {
        "event_type": "ApplicationApproved",
        "event_version": 1,
        "payload": {
            "application_id": application_id,
            "approved_amount_usd": approved_amount_usd,
            "interest_rate": interest_rate,
            "approved_by": approved_by,
            "effective_date": effective_date,
        }
    }
    
    # 4. Append with causal chain tracking
    await store.append(
        f"loan-{application_id}",
        [event],
        expected_version=agg.version,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
    
    return {
        "status": "approved",
        "application_id": application_id,
        "approved_amount_usd": approved_amount_usd,
    }


# ─── AGENT SESSION COMMANDS ────────────────────────────────────────────────

async def handle_start_agent_session(
    store,
    agent_id: str,
    session_id: str,
    agent_type: str,
    model_version: str,
    context_source: str,
    context_token_count: int,
) -> dict:
    """
    Handle Start Agent Session command.
    
    This implements the Gas Town pattern - context must be loaded
    before any agent can make decisions.
    """
    from src.aggregates.agent_session import AgentSessionAggregate
    
    # 1. Create new aggregate
    agg = AgentSessionAggregate(agent_id=agent_id, session_id=session_id)
    
    # 2. Validate (session is new)
    if agg.version > 0:
        raise ValueError("Session already exists")
    
    # 3. Determine events
    event = {
        "event_type": "AgentContextLoaded",
        "event_version": 1,
        "payload": {
            "agent_id": agent_id,
            "session_id": session_id,
            "context_source": context_source,
            "context_token_count": context_token_count,
            "model_version": model_version,
        }
    }
    
    # 4. Append
    await store.append(
        f"agent-{agent_id}-{session_id}",
        [event],
        expected_version=-1,
    )
    
    return {
        "status": "session_started",
        "agent_id": agent_id,
        "session_id": session_id,
    }
