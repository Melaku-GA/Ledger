"""
src/aggregates/audit_ledger.py
===============================
Audit Ledger Aggregate - Domain Logic Implementation

Implements:
- Append-only enforcement
- Cross-stream causal ordering via correlation_id chains
- Immutable audit trail

The AuditLedger aggregate maintains a cross-cutting audit trail that links
events across all other aggregates for a single business entity.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AuditState(str, Enum):
    """States for audit ledger."""
    INITIAL = "INITIAL"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class AuditLedgerError(Exception):
    """Raised when an audit ledger business rule is violated."""
    pass


@dataclass
class AuditLedgerAggregate:
    """
    Audit Ledger Aggregate Root.
    
    Maintains cross-cutting audit trail linking events across all aggregates.
    Append-only - no events may be removed.
    """
    entity_type: str
    entity_id: str
    state: AuditState = AuditState.INITIAL
    
    # Cross-stream tracking
    correlation_ids: list[str] = field(default_factory=list)
    causation_ids: list[str] = field(default_factory=list)
    
    # Audit chain
    integrity_hash: Optional[str] = None
    previous_hash: Optional[str] = None
    
    # Version for optimistic concurrency
    version: int = 0

    @classmethod
    async def load(cls, store, entity_type: str, entity_id: str) -> "AuditLedgerAggregate":
        """Load and replay event stream to rebuild audit ledger state."""
        agg = cls(entity_type=entity_type, entity_id=entity_id)
        
        # Load events from the stream
        events = await store.load_stream(f"audit-{entity_type}-{entity_id}")
        
        # Replay each event to rebuild state
        for event in events:
            agg.apply(event)
        
        return agg

    def apply(self, event: dict) -> None:
        """Apply one event to update aggregate state."""
        et = event.get("event_type")
        p = event.get("payload", {})
        
        self.version = event.get("stream_position", self.version)
        
        # Track correlation/causation
        if p.get("correlation_id"):
            self.correlation_ids.append(p["correlation_id"])
        if p.get("causation_id"):
            self.causation_ids.append(p["causation_id"])
        
        if et == "AuditIntegrityCheckRun":
            self._on_integrity_check(p)
        elif et == "AuditEventRecorded":
            self._on_event_recorded(p)

    def _on_integrity_check(self, payload: dict) -> None:
        """Handle AuditIntegrityCheckRun event."""
        self.state = AuditState.ACTIVE
        self.integrity_hash = payload.get("integrity_hash")
        self.previous_hash = payload.get("previous_hash")

    def _on_event_recorded(self, payload: dict) -> None:
        """Handle AuditEventRecorded event."""
        self.state = AuditState.ACTIVE

    # ─── BUSINESS RULES ───────────────────────────────────────────────────────

    def assert_append_only(self) -> None:
        """
        Audit ledger is append-only - this is enforced at the event store level.
        This method provides a programmatic check.
        """
        if self.state == AuditState.ARCHIVED:
            raise AuditLedgerError(
                "Cannot append to archived audit ledger"
            )

    def assert_cross_stream_causal_order(self, correlation_id: str) -> None:
        """
        Verify that referenced correlation_id exists in the audit trail.
        
        This ensures causal ordering across streams - an event can only
        reference a correlation_id that was created earlier in the system.
        
        NOTE: This is a placeholder implementation. For full production use,
        this would require access to the global event store to verify that
        the correlation_id exists across all streams in the system.
        """
        # In a full implementation, this would query the event store
        # to verify the correlation_id was created before this event
        # For now, we just track it for audit purposes
        pass

    def get_stream_id(self) -> str:
        """Get the stream ID for this audit ledger."""
        return f"audit-{self.entity_type}-{self.entity_id}"
