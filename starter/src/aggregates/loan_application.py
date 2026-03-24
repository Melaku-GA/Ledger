"""
src/aggregates/loan_application.py
===================================
Loan Application Aggregate - Domain Logic

Implements the state machine and business rules for loan applications.
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class ApplicationState(str, Enum):
    """States for a loan application."""
    INITIAL = "INITIAL"
    SUBMITTED = "SUBMITTED"
    CREDIT_ANALYSIS_REQUESTED = "CREDIT_ANALYSIS_REQUESTED"
    CREDIT_ANALYSIS_COMPLETE = "CREDIT_ANALYSIS_COMPLETE"
    FRAUD_SCREENING_REQUESTED = "FRAUD_SCREENING_REQUESTED"
    FRAUD_SCREENING_COMPLETE = "FRAUD_SCREENING_COMPLETE"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    PENDING_DECISION = "PENDING_DECISION"
    APPROVED_PENDING_HUMAN = "APPROVED_PENDING_HUMAN"
    DECLINED_PENDING_HUMAN = "DECLINED_PENDING_HUMAN"
    FINAL_APPROVED = "FINAL_APPROVED"
    FINAL_DECLINED = "FINAL_DECLINED"


# Valid state transitions
VALID_TRANSITIONS = {
    ApplicationState.INITIAL: [ApplicationState.SUBMITTED],
    ApplicationState.SUBMITTED: [ApplicationState.CREDIT_ANALYSIS_REQUESTED],
    ApplicationState.CREDIT_ANALYSIS_REQUESTED: [ApplicationState.CREDIT_ANALYSIS_COMPLETE],
    ApplicationState.CREDIT_ANALYSIS_COMPLETE: [ApplicationState.FRAUD_SCREENING_REQUESTED],
    ApplicationState.FRAUD_SCREENING_REQUESTED: [ApplicationState.FRAUD_SCREENING_COMPLETE],
    ApplicationState.FRAUD_SCREENING_COMPLETE: [ApplicationState.COMPLIANCE_REVIEW],
    ApplicationState.COMPLIANCE_REVIEW: [ApplicationState.PENDING_DECISION],
    ApplicationState.PENDING_DECISION: [ApplicationState.APPROVED_PENDING_HUMAN, ApplicationState.DECLINED_PENDING_HUMAN],
    ApplicationState.APPROVED_PENDING_HUMAN: [ApplicationState.FINAL_APPROVED],
    ApplicationState.DECLINED_PENDING_HUMAN: [ApplicationState.FINAL_DECLINED],
}


class DomainError(Exception):
    """Raised when a business rule is violated."""
    pass


@dataclass
class LoanApplicationAggregate:
    """Loan Application Aggregate Root."""
    application_id: str
    state: ApplicationState = ApplicationState.INITIAL
    applicant_id: Optional[str] = None
    requested_amount_usd: Optional[float] = None
    approved_amount_usd: Optional[float] = None
    interest_rate: Optional[float] = None
    risk_tier: Optional[str] = None
    decision: Optional[str] = None
    version: int = 0
    
    @classmethod
    async def load(cls, store, application_id: str) -> "LoanApplicationAggregate":
        """Load and replay events to rebuild state."""
        stream_id = f"loan-{application_id}"
        events = await store.load_stream(stream_id)
        
        agg = cls(application_id=application_id)
        if events:
            for event in events:
                agg.apply(event)
        else:
            # New stream - set version to -1 so append works with expected_version=-1
            agg.version = -1
        return agg
    
    def apply(self, event: dict) -> None:
        """Apply an event to update state."""
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        
        # Use stream_position directly as version
        # Stream position is 1-indexed, so this matches the store's version
        self.version = event.get("stream_position", self.version)
        
        if event_type == "ApplicationSubmitted":
            self.state = ApplicationState.SUBMITTED
            self.applicant_id = payload.get("applicant_id")
            self.requested_amount_usd = payload.get("requested_amount_usd")
        
        elif event_type == "CreditAnalysisRequested":
            self.state = ApplicationState.CREDIT_ANALYSIS_REQUESTED
        
        elif event_type == "CreditAnalysisCompleted":
            self.state = ApplicationState.CREDIT_ANALYSIS_COMPLETE
            self.risk_tier = payload.get("risk_tier")
        
        elif event_type == "FraudScreeningCompleted":
            self.state = ApplicationState.COMPLIANCE_REVIEW
        
        elif event_type == "ComplianceCheckRequested":
            self.state = ApplicationState.COMPLIANCE_REVIEW
        
        elif event_type == "DecisionGenerated":
            self.state = ApplicationState.PENDING_DECISION
            self.decision = payload.get("recommendation")
        
        elif event_type == "HumanReviewCompleted":
            if payload.get("override", False):
                self.decision = payload.get("final_decision")
            if payload.get("final_decision") == "APPROVE":
                self.state = ApplicationState.APPROVED_PENDING_HUMAN
            else:
                self.state = ApplicationState.DECLINED_PENDING_HUMAN
        
        elif event_type == "ApplicationApproved":
            self.state = ApplicationState.FINAL_APPROVED
            self.approved_amount_usd = payload.get("approved_amount_usd")
            self.interest_rate = payload.get("interest_rate")
        
        elif event_type == "ApplicationDeclined":
            self.state = ApplicationState.FINAL_DECLINED
    
    def assert_can_submit_application(self) -> None:
        """Can submit a new application."""
        if self.state != ApplicationState.INITIAL:
            raise DomainError(f"Cannot submit: current state is {self.state}")
    
    def assert_can_complete_credit_analysis(self) -> None:
        """Can complete credit analysis."""
        if self.state not in [ApplicationState.CREDIT_ANALYSIS_REQUESTED, ApplicationState.SUBMITTED]:
            raise DomainError(f"Cannot complete credit analysis: current state is {self.state}")
    
    def assert_can_generate_decision(self) -> None:
        """Can generate decision."""
        if self.state not in [ApplicationState.COMPLIANCE_REVIEW, ApplicationState.FRAUD_SCREENING_COMPLETE]:
            raise DomainError(f"Cannot generate decision: current state is {self.state}")
    
    def assert_can_approve(self) -> None:
        """Can approve application."""
        if self.state not in [ApplicationState.APPROVED_PENDING_HUMAN]:
            raise DomainError(f"Cannot approve: current state is {self.state}")
    
    def assert_can_complete_fraud_screening(self) -> None:
        """Can complete fraud screening."""
        if self.state not in [ApplicationState.FRAUD_SCREENING_REQUESTED, ApplicationState.CREDIT_ANALYSIS_COMPLETE]:
            raise DomainError(f"Cannot complete fraud screening: current state is {self.state}")
    
    def assert_valid_transition(self, target: ApplicationState) -> None:
        """Assert state transition is valid."""
        allowed = VALID_TRANSITIONS.get(self.state, [])
        if target not in allowed:
            raise DomainError(f"Invalid transition: {self.state} -> {target}")
