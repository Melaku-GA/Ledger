"""
src/aggregates/compliance_record.py
===================================
Compliance Record Aggregate - Domain Logic Implementation

Implements:
- Mandatory check tracking
- Regulation version references
- Compliance state machine

The ComplianceRecord aggregate tracks regulatory checks for each application.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ComplianceState(str, Enum):
    """States for compliance record."""
    INITIAL = "INITIAL"
    CHECKS_REQUESTED = "CHECKS_REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


VALID_COMPLIANCE_TRANSITIONS = {
    ComplianceState.INITIAL: [ComplianceState.CHECKS_REQUESTED],
    ComplianceState.CHECKS_REQUESTED: [ComplianceState.IN_PROGRESS],
    ComplianceState.IN_PROGRESS: [ComplianceState.PASSED, ComplianceState.FAILED],
    ComplianceState.PASSED: [],
    ComplianceState.FAILED: [],
}


class ComplianceRecordError(Exception):
    """Raised when a compliance business rule is violated."""
    pass


@dataclass
class ComplianceRecordAggregate:
    """
    Compliance Record Aggregate Root.
    
    Tracks regulatory checks, rule evaluations, and compliance verdicts
    for each loan application.
    """
    application_id: str
    state: ComplianceState = ComplianceState.INITIAL
    
    # Regulation tracking
    regulation_set_version: Optional[str] = None
    checks_required: list[str] = field(default_factory=list)
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    
    # Version for optimistic concurrency
    version: int = 0

    @classmethod
    async def load(cls, store, application_id: str) -> "ComplianceRecordAggregate":
        """Load and replay event stream to rebuild compliance record state."""
        agg = cls(application_id=application_id)
        
        # Load events from the stream
        events = await store.load_stream(f"compliance-{application_id}")
        
        # Replay each event to rebuild state
        for event in events:
            agg.apply(event)
        
        return agg

    def apply(self, event: dict) -> None:
        """Apply one event to update aggregate state."""
        et = event.get("event_type")
        p = event.get("payload", {})
        
        self.version = event.get("stream_position", self.version)
        
        if et == "ComplianceCheckRequested":
            self._on_check_requested(p)
        elif et == "ComplianceRulePassed":
            self._on_rule_passed(p)
        elif et == "ComplianceRuleFailed":
            self._on_rule_failed(p)

    def _on_check_requested(self, payload: dict) -> None:
        """Handle ComplianceCheckRequested event."""
        self.state = ComplianceState.CHECKS_REQUESTED
        self.regulation_set_version = payload.get("regulation_set_version")
        self.checks_required = payload.get("checks_required", [])

    def _on_rule_passed(self, payload: dict) -> None:
        """Handle ComplianceRulePassed event."""
        self.state = ComplianceState.IN_PROGRESS
        rule_id = payload.get("rule_id")
        if rule_id and rule_id not in self.checks_passed:
            self.checks_passed.append(rule_id)
        
        # Check if all required checks have passed
        if set(self.checks_required).issubset(set(self.checks_passed)):
            self.state = ComplianceState.PASSED

    def _on_rule_failed(self, payload: dict) -> None:
        """Handle ComplianceRuleFailed event."""
        self.state = ComplianceState.FAILED
        rule_id = payload.get("rule_id")
        if rule_id and rule_id not in self.checks_failed:
            self.checks_failed.append(rule_id)

    # ─── BUSINESS RULES ───────────────────────────────────────────────────────

    def assert_all_required_checks_present(self) -> None:
        """
        Assert that all required compliance checks have been performed.
        """
        missing = set(self.checks_required) - set(self.checks_passed) - set(self.checks_failed)
        if missing:
            raise ComplianceRecordError(
                f"Cannot approve application: missing compliance checks: {missing}"
            )

    def assert_no_failed_checks(self) -> None:
        """
        Assert that no compliance checks have failed.
        """
        if self.checks_failed:
            raise ComplianceRecordError(
                f"Cannot approve application: failed compliance checks: {self.checks_failed}"
            )

    def assert_valid_transition(self, target: ComplianceState) -> None:
        """Assert that a compliance state transition is valid."""
        allowed = VALID_COMPLIANCE_TRANSITIONS.get(self.state, [])
        if target not in allowed:
            raise ComplianceRecordError(
                f"Invalid compliance state transition: {self.state.value} → {target.value}"
            )
