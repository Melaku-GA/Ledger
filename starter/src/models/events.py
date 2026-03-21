"""
src/models/events.py
=====================
Pydantic models for The Ledger Event Store

Phase 1: Core event models
- BaseEvent: Abstract base for all events
- StoredEvent: Event as stored in the database
- StreamMetadata: Metadata about an event stream
- Custom exceptions for event store operations
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4
import json

from pydantic import BaseModel, Field


# ─── CUSTOM EXCEPTIONS ────────────────────────────────────────────────────────


class EventStoreError(Exception):
    """Base exception for all event store errors."""
    pass


class OptimisticConcurrencyError(EventStoreError):
    """
    Raised when expected_version doesn't match current stream version.
    
    This is the critical concurrency control mechanism - two agents
    attempting to append to the same stream simultaneously will have
    one succeed and one raise this error.
    """
    def __init__(self, stream_id: str, expected: int, actual: int):
        self.stream_id = stream_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"OptimisticConcurrencyError on stream '{stream_id}': "
            f"expected version {expected}, actual version {actual}"
        )


class DomainError(EventStoreError):
    """Raised when a business rule is violated."""
    def __init__(self, message: str, stream_id: Optional[str] = None):
        self.stream_id = stream_id
        super().__init__(message)


class StreamNotFoundError(EventStoreError):
    """Raised when attempting to load a stream that doesn't exist."""
    def __init__(self, stream_id: str):
        self.stream_id = stream_id
        super().__init__(f"Stream not found: {stream_id}")


# ─── ENUMS ───────────────────────────────────────────────────────────────────


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ApplicationState(str, Enum):
    SUBMITTED = "SUBMITTED"
    DOCUMENTS_PENDING = "DOCUMENTS_PENDING"
    DOCUMENTS_UPLOADED = "DOCUMENTS_UPLOADED"
    DOCUMENTS_PROCESSED = "DOCUMENTS_PROCESSED"
    CREDIT_ANALYSIS_REQUESTED = "CREDIT_ANALYSIS_REQUESTED"
    CREDIT_ANALYSIS_COMPLETE = "CREDIT_ANALYSIS_COMPLETE"
    FRAUD_SCREENING_REQUESTED = "FRAUD_SCREENING_REQUESTED"
    FRAUD_SCREENING_COMPLETE = "FRAUD_SCREENING_COMPLETE"
    COMPLIANCE_CHECK_REQUESTED = "COMPLIANCE_CHECK_REQUESTED"
    COMPLIANCE_CHECK_COMPLETE = "COMPLIANCE_CHECK_COMPLETE"
    PENDING_DECISION = "PENDING_DECISION"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    DECLINED_COMPLIANCE = "DECLINED_COMPLIANCE"
    REFERRED = "REFERRED"


class LoanPurpose(str, Enum):
    WORKING_CAPITAL = "working_capital"
    EQUIPMENT_FINANCING = "equipment_financing"
    REAL_ESTATE = "real_estate"
    EXPANSION = "expansion"
    REFINANCING = "refinancing"
    ACQUISITION = "acquisition"
    BRIDGE = "bridge"


class AgentType(str, Enum):
    DOCUMENT_PROCESSING = "document_processing"
    CREDIT_ANALYSIS = "credit_analysis"
    FRAUD_DETECTION = "fraud_detection"
    COMPLIANCE = "compliance"
    DECISION_ORCHESTRATOR = "decision_orchestrator"


class RecommendationType(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    REFER = "REFER"


# ─── BASE EVENT ───────────────────────────────────────────────────────────────


class BaseEvent(BaseModel):
    """
    Abstract base for all domain events.
    
    Events are immutable records of something that happened in the domain.
    Once recorded, they should never be modified.
    """
    event_type: str
    event_version: int = 1
    event_id: UUID = Field(default_factory=uuid4)
    recorded_at: Optional[datetime] = None

    def to_payload(self) -> dict:
        """
        Convert event to payload dict for storage.
        Removes metadata fields from the payload.
        """
        d = self.model_dump(mode='json')
        for k in ('event_type', 'event_version', 'event_id', 'recorded_at'):
            d.pop(k, None)
        return d

    def to_store_dict(self) -> dict:
        """Convert event to dict for storage in event store."""
        return {
            "event_type": self.event_type,
            "event_version": self.event_version,
            "payload": self.to_payload(),
        }

    class Config:
        from_attributes = True


# ─── STORED EVENT ─────────────────────────────────────────────────────────────


class StoredEvent(BaseModel):
    """
    Event as stored in the event store database.
    
    Contains all fields from the database plus convenience accessors.
    """
    event_id: UUID
    stream_id: str
    stream_position: int
    global_position: int
    event_type: str
    event_version: int
    payload: dict
    metadata: dict = Field(default_factory=dict)
    recorded_at: datetime

    def to_dict(self) -> dict:
        """Convert to dictionary for application use."""
        return self.model_dump()

    class Config:
        from_attributes = True


# ─── STREAM METADATA ─────────────────────────────────────────────────────────


class StreamMetadata(BaseModel):
    """
    Metadata about an event stream (aggregate).
    
    Contains information about the stream's current state,
    creation time, and optional archival information.
    """
    stream_id: str
    aggregate_type: str
    current_version: int
    created_at: datetime
    archived_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)

    class Config:
        from_attributes = True


# ─── EVENT CATALOGUE: Core Events for Apex Financial ───────────────────────


class ApplicationSubmitted(BaseEvent):
    """Event recorded when a loan application is submitted."""
    event_type: str = "ApplicationSubmitted"
    application_id: str
    applicant_id: str
    requested_amount_usd: Decimal
    loan_purpose: LoanPurpose
    submission_channel: str
    contact_email: str
    contact_name: str
    submitted_at: datetime


class CreditAnalysisRequested(BaseEvent):
    """Event recorded when credit analysis is requested for an application."""
    event_type: str = "CreditAnalysisRequested"
    application_id: str
    assigned_agent_id: str
    requested_at: datetime
    priority: str = "NORMAL"


class CreditAnalysisCompleted(BaseEvent):
    """Event recorded when credit analysis is completed by an agent."""
    event_type: str = "CreditAnalysisCompleted"
    event_version: int = 2  # v2 adds model_version
    application_id: str
    agent_id: str
    session_id: str
    model_version: Optional[str] = None
    confidence_score: Optional[float] = None
    risk_tier: Optional[RiskTier] = None
    recommended_limit_usd: Optional[Decimal] = None
    analysis_duration_ms: Optional[int] = None
    input_data_hash: Optional[str] = None


class FraudScreeningCompleted(BaseEvent):
    """Event recorded when fraud screening is completed."""
    event_type: str = "FraudScreeningCompleted"
    application_id: str
    agent_id: str
    fraud_score: float
    anomaly_flags: list[str] = Field(default_factory=list)
    screening_model_version: str
    input_data_hash: Optional[str] = None


class ComplianceCheckRequested(BaseEvent):
    """Event recorded when compliance check is requested."""
    event_type: str = "ComplianceCheckRequested"
    application_id: str
    regulation_set_version: str
    checks_required: list[str] = Field(default_factory=list)


class ComplianceRulePassed(BaseEvent):
    """Event recorded when a compliance rule passes."""
    event_type: str = "ComplianceRulePassed"
    application_id: str
    rule_id: str
    rule_version: str
    evaluation_timestamp: datetime
    evidence_hash: Optional[str] = None


class ComplianceRuleFailed(BaseEvent):
    """Event recorded when a compliance rule fails."""
    event_type: str = "ComplianceRuleFailed"
    application_id: str
    rule_id: str
    rule_version: str
    failure_reason: str
    remediation_required: Optional[str] = None


class DecisionGenerated(BaseEvent):
    """Event recorded when the decision orchestrator generates a decision."""
    event_type: str = "DecisionGenerated"
    event_version: int = 2  # v2 adds model_versions dict
    application_id: str
    orchestrator_agent_id: str
    recommendation: RecommendationType
    confidence_score: float
    contributing_agent_sessions: list[str] = Field(default_factory=list)
    decision_basis_summary: str
    model_versions: dict[str, str] = Field(default_factory=dict)


class HumanReviewCompleted(BaseEvent):
    """Event recorded when a human reviewer completes their review."""
    event_type: str = "HumanReviewCompleted"
    application_id: str
    reviewer_id: str
    override: bool
    final_decision: str
    override_reason: Optional[str] = None
    reviewed_at: datetime


class ApplicationApproved(BaseEvent):
    """Event recorded when an application is approved."""
    event_type: str = "ApplicationApproved"
    application_id: str
    approved_amount_usd: Decimal
    interest_rate: float
    conditions: list[str] = Field(default_factory=list)
    approved_by: str  # human_id or "auto"
    effective_date: str


class ApplicationDeclined(BaseEvent):
    """Event recorded when an application is declined."""
    event_type: str = "ApplicationDeclined"
    application_id: str
    decline_reasons: list[str]
    declined_by: str
    adverse_action_notice_required: bool


class AgentContextLoaded(BaseEvent):
    """
    Event recorded when an agent loads its context (Gas Town pattern).
    This must be the first event in any agent session before decisions can be made.
    """
    event_type: str = "AgentContextLoaded"
    agent_id: str
    session_id: str
    context_source: str
    event_replay_from_position: Optional[int] = None
    context_token_count: int
    model_version: str


class AuditIntegrityCheckRun(BaseEvent):
    """Event recorded when an integrity check is run on the audit chain."""
    event_type: str = "AuditIntegrityCheckRun"
    entity_id: str
    check_timestamp: datetime
    events_verified_count: int
    integrity_hash: str
    previous_hash: Optional[str] = None


# ─── EVENT REGISTRY ───────────────────────────────────────────────────────────

# Registry for validating events by type
EVENT_REGISTRY: dict[str, type[BaseEvent]] = {
    "ApplicationSubmitted": ApplicationSubmitted,
    "CreditAnalysisRequested": CreditAnalysisRequested,
    "CreditAnalysisCompleted": CreditAnalysisCompleted,
    "FraudScreeningCompleted": FraudScreeningCompleted,
    "ComplianceCheckRequested": ComplianceCheckRequested,
    "ComplianceRulePassed": ComplianceRulePassed,
    "ComplianceRuleFailed": ComplianceRuleFailed,
    "DecisionGenerated": DecisionGenerated,
    "HumanReviewCompleted": HumanReviewCompleted,
    "ApplicationApproved": ApplicationApproved,
    "ApplicationDeclined": ApplicationDeclined,
    "AgentContextLoaded": AgentContextLoaded,
    "AuditIntegrityCheckRun": AuditIntegrityCheckRun,
}
