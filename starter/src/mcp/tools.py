"""
src/mcp/tools.py
=================
MCP Tools - Command side (write operations)

Implements the 8 MCP tools for The Ledger:
1. submit_application - ApplicationSubmitted
2. record_credit_analysis - CreditAnalysisCompleted
3. record_fraud_screening - FraudScreeningCompleted
4. record_compliance_check - ComplianceRulePassed/Failed
5. generate_decision - DecisionGenerated
6. record_human_review - HumanReviewCompleted
7. start_agent_session - AgentContextLoaded
8. run_integrity_check - AuditIntegrityCheckRun

Key Design:
- Structured error types, not messages
- Precondition documentation in tool descriptions
- Returns stream_id, event_id for traceability
"""
from typing import Optional, Any
from dataclasses import dataclass


# ─── Tool Result Types ────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Base result for MCP tools."""
    success: bool
    data: dict
    error: Optional[dict] = None


@dataclass
class PreconditionError:
    """Structured error for preconditions."""
    error_type: str
    message: str
    suggested_action: str
    

@dataclass
class OptimisticConcurrencyErrorResult:
    """Structured error for OCC."""
    error_type: str = "OptimisticConcurrencyError"
    stream_id: str = ""
    expected: int = 0
    actual: int = 0
    message: str = ""
    suggested_action: str = "reload_stream_and_retry"


# ─── Tool Implementations ───────────────────────────────────────────────────

async def submit_application(
    store,
    application_id: str,
    applicant_id: str,
    requested_amount_usd: float,
    loan_purpose: str,
    submission_channel: str = "API",
) -> ToolResult:
    """
    Submit a new loan application.
    
    Preconditions:
    - application_id must be unique (not already exist)
    
    Returns: stream_id, initial_version
    """
    from src.commands.handlers import handle_submit_application
    
    try:
        result = await handle_submit_application(
            store=store,
            application_id=application_id,
            applicant_id=applicant_id,
            requested_amount_usd=requested_amount_usd,
            loan_purpose=loan_purpose,
            submission_channel=submission_channel,
        )
        
        return ToolResult(
            success=True,
            data={
                "stream_id": f"loan-{application_id}",
                "application_id": application_id,
                "status": result.get("status"),
            }
        )
    except Exception as e:
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": "SubmissionError",
                "message": str(e),
                "suggested_action": "check_application_id_uniqueness"
            }
        )


async def record_credit_analysis(
    store,
    application_id: str,
    agent_id: str,
    session_id: str,
    model_version: str,
    confidence_score: float,
    risk_tier: str,
    recommended_limit_usd: float,
    input_data: dict,
) -> ToolResult:
    """
    Record credit analysis completed event.
    
    Preconditions:
    - Application must exist in CREDIT_ANALYSIS_REQUESTED state
    - Agent must have active AgentSession with context loaded (Gas Town)
    - Model version must match session's model version
    
    Returns: event_id, new_stream_version
    """
    from src.commands.handlers import handle_credit_analysis_completed
    
    try:
        result = await handle_credit_analysis_completed(
            store=store,
            application_id=application_id,
            agent_id=agent_id,
            session_id=session_id,
            model_version=model_version,
            confidence_score=confidence_score,
            risk_tier=risk_tier,
            recommended_limit_usd=recommended_limit_usd,
            input_data=input_data,
        )
        
        return ToolResult(
            success=True,
            data={
                "event_id": f"credit-{application_id}-{session_id}",
                "application_id": application_id,
                "confidence_score": confidence_score,
                "status": result.get("status"),
            }
        )
    except Exception as e:
        error_type = "ExecutionError"
        suggested = "check_application_state"
        
        # Check for specific error types
        if "context" in str(e).lower():
            error_type = "PreconditionFailed"
            suggested = "call_start_agent_session_first"
        elif "OptimisticConcurrencyError" in str(e):
            error_type = "OptimisticConcurrencyError"
            suggested = "reload_stream_and_retry"
        
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": error_type,
                "message": str(e),
                "suggested_action": suggested
            }
        )


async def record_fraud_screening(
    store,
    application_id: str,
    agent_id: str,
    session_id: str,
    fraud_score: float,
    anomaly_flags: list[str],
    screening_model_version: str,
    input_data: dict,
) -> ToolResult:
    """
    Record fraud screening completed event.
    
    Preconditions:
    - Application must exist
    - Agent must have active session with context loaded
    
    Returns: event_id, new_stream_version
    """
    from src.commands.handlers import handle_fraud_screening_completed
    
    try:
        result = await handle_fraud_screening_completed(
            store=store,
            application_id=application_id,
            agent_id=agent_id,
            session_id=session_id,
            fraud_score=fraud_score,
            anomaly_flags=anomaly_flags,
            screening_model_version=screening_model_version,
            input_data=input_data,
        )
        
        return ToolResult(
            success=True,
            data={
                "event_id": f"fraud-{application_id}-{session_id}",
                "application_id": application_id,
                "fraud_score": fraud_score,
            }
        )
    except Exception as e:
        error_type = "ExecutionError"
        suggested = "check_application_state"
        
        if "context" in str(e).lower():
            error_type = "PreconditionFailed"
            suggested = "call_start_agent_session_first"
        elif "OptimisticConcurrencyError" in str(e):
            error_type = "OptimisticConcurrencyError"
            suggested = "reload_stream_and_retry"
        
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": error_type,
                "message": str(e),
                "suggested_action": suggested
            }
        )


async def record_compliance_check(
    store,
    application_id: str,
    rule_id: str,
    rule_version: str,
    passed: bool,
    evidence_hash: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> ToolResult:
    """
    Record compliance check result.
    
    Preconditions:
    - Application must exist
    - Regulation set version must be valid
    
    Returns: check_id, compliance_status
    """
    from src.commands.handlers import handle_compliance_check
    
    try:
        result = await handle_compliance_check(
            store=store,
            application_id=application_id,
            rule_id=rule_id,
            rule_version=rule_version,
            passed=passed,
            evidence_hash=evidence_hash,
            failure_reason=failure_reason,
        )
        
        return ToolResult(
            success=True,
            data={
                "check_id": f"compliance-{application_id}-{rule_id}",
                "application_id": application_id,
                "rule_id": rule_id,
                "compliance_status": "PASSED" if passed else "FAILED",
            }
        )
    except Exception as e:
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": "ExecutionError",
                "message": str(e),
                "suggested_action": "check_regulation_version"
            }
        )


async def generate_decision(
    store,
    application_id: str,
    orchestrator_agent_id: str,
    confidence_score: float,
    recommendation: str,
    contributing_sessions: list[str],
) -> ToolResult:
    """
    Generate decision recommendation.
    
    Preconditions:
    - All required analyses must be complete
    - Confidence floor: confidence < 0.6 → forced referral
    
    Returns: decision_id, recommendation
    """
    from src.commands.handlers import handle_generate_decision
    
    try:
        # Apply confidence floor rule
        if confidence_score < 0.6:
            recommendation = "REFER"
        
        result = await handle_generate_decision(
            store=store,
            application_id=application_id,
            orchestrator_agent_id=orchestrator_agent_id,
            confidence_score=confidence_score,
            recommendation=recommendation,
            contributing_sessions=contributing_sessions,
        )
        
        return ToolResult(
            success=True,
            data={
                "decision_id": f"decision-{application_id}",
                "application_id": application_id,
                "recommendation": result.get("recommendation"),
                "confidence_score": confidence_score,
            }
        )
    except Exception as e:
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": "ExecutionError",
                "message": str(e),
                "suggested_action": "check_all_analyses_complete"
            }
        )


async def record_human_review(
    store,
    application_id: str,
    reviewer_id: str,
    override: bool,
    final_decision: str,
    override_reason: Optional[str] = None,
) -> ToolResult:
    """
    Record human review completion.
    
    Preconditions:
    - reviewer_id authentication (passed in request)
    - if override=True, override_reason is required
    
    Returns: final_decision, application_state
    """
    from src.commands.handlers import handle_human_review
    
    try:
        result = await handle_human_review(
            store=store,
            application_id=application_id,
            reviewer_id=reviewer_id,
            override=override,
            final_decision=final_decision,
            override_reason=override_reason,
        )
        
        return ToolResult(
            success=True,
            data={
                "application_id": application_id,
                "final_decision": final_decision,
                "reviewer_id": reviewer_id,
            }
        )
    except Exception as e:
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": "ExecutionError",
                "message": str(e),
                "suggested_action": "provide_override_reason_if_required"
            }
        )


async def start_agent_session(
    store,
    agent_id: str,
    session_id: str,
    agent_type: str,
    model_version: str,
    context_source: str,
    context_token_count: int,
) -> ToolResult:
    """
    Start a new agent session.
    
    This implements the Gas Town pattern - context must be loaded
    before any agent can make decisions.
    
    Preconditions:
    - Must be called before any decision tools
    
    Returns: session_id, context_position
    """
    from src.commands.handlers import handle_start_agent_session
    
    try:
        result = await handle_start_agent_session(
            store=store,
            agent_id=agent_id,
            session_id=session_id,
            agent_type=agent_type,
            model_version=model_version,
            context_source=context_source,
            context_token_count=context_token_count,
        )
        
        return ToolResult(
            success=True,
            data={
                "session_id": session_id,
                "agent_id": agent_id,
                "model_version": model_version,
                "context_token_count": context_token_count,
            }
        )
    except Exception as e:
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": "ExecutionError",
                "message": str(e),
                "suggested_action": "check_session_not_already_started"
            }
        )


async def run_integrity_check(
    store,
    entity_type: str,
    entity_id: str,
) -> ToolResult:
    """
    Run integrity check on an entity's event stream.
    
    Preconditions:
    - Can only be called by compliance role
    - Rate-limited to 1/minute per entity
    
    Returns: check_result, chain_valid
    """
    from src.integrity.audit_chain import run_integrity_check as check
    
    try:
        result = await check(store, entity_type, entity_id)
        
        return ToolResult(
            success=True,
            data={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "events_verified": result.events_verified,
                "chain_valid": result.chain_valid,
                "tamper_detected": result.tamper_detected,
                "new_hash": result.new_hash,
            }
        )
    except Exception as e:
        return ToolResult(
            success=False,
            data={},
            error={
                "error_type": "IntegrityCheckError",
                "message": str(e),
                "suggested_action": "retry_after_rate_limit"
            }
        )
