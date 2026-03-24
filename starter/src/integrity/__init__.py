"""
src/integrity/__init__.py
=========================
Integrity package for The Ledger - audit chains and Gas Town pattern.
"""
from src.integrity.audit_chain import (
    IntegrityCheckResult,
    run_integrity_check,
    compute_event_hash,
    verify_event_integrity,
)
from src.integrity.gas_town import (
    AgentContext,
    reconstruct_agent_context,
    detect_partial_decision,
)

__all__ = [
    "IntegrityCheckResult",
    "run_integrity_check",
    "compute_event_hash",
    "verify_event_integrity",
    "AgentContext",
    "reconstruct_agent_context",
    "detect_partial_decision",
]
