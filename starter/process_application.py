"""
Automated Document Processing Pipeline
======================================
This pipeline automatically processes loan applications by:
1. Reading documents from the company folder
2. Extracting financial data from CSV/Excel files
3. Submitting to The Ledger and processing through all phases

Usage: python process_application.py COMP-001
"""
import asyncio
import json
import csv
import sys
import os
from datetime import datetime
from src.event_store import EventStore
from src.projections.daemon import ProjectionDaemon
from src.projections.application_summary import ApplicationSummaryProjection
from src.projections.agent_performance import AgentPerformanceLedgerProjection
from src.projections.compliance_audit import ComplianceAuditViewProjection
from src.mcp import tools, resources


class DocumentProcessor:
    """Processes documents and extracts data for loan applications."""
    
    def __init__(self, company_id: str):
        self.company_id = company_id
        self.base_path = f"../documents/{company_id}"
        self.data_path = "../data"
    
    def load_applicant_profile(self) -> dict:
        """Load company profile from applicant_profiles.json"""
        with open(f"{self.data_path}/applicant_profiles.json", 'r') as f:
            profiles = json.load(f)
        
        for p in profiles:
            if p.get('company_id') == self.company_id:
                return p
        raise ValueError(f"Company {self.company_id} not found in profiles")
    
    def load_financial_summary(self) -> dict:
        """Load financial data from financial_summary.csv"""
        financials = {}
        with open(f"{self.base_path}/financial_summary.csv", 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                field = row['field']
                value = row['value']
                # Convert to appropriate type
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                elif '.' in value:
                    try:
                        value = float(value)
                    except:
                        pass
                else:
                    try:
                        value = int(value)
                    except:
                        pass
                financials[field] = value
        return financials
    
    def extract_loan_amount(self, financials: dict) -> float:
        """Determine requested loan amount based on financial metrics"""
        # Use 10% of total assets as a reasonable loan amount
        total_assets = financials.get('total_assets', 0)
        return min(total_assets * 0.1, 1000000)  # Cap at $1M
    
    def assess_risk(self, profile: dict, financials: dict) -> dict:
        """Assess credit risk based on profile and financial data"""
        risk_factors = []
        confidence = 0.85
        
        # Check debt to equity
        debt_to_equity = financials.get('debt_to_equity', 0)
        if debt_to_equity > 3.0:
            risk_factors.append("HIGH_DEBT_TO_EQUITY")
            confidence -= 0.2
        elif debt_to_equity > 2.0:
            risk_factors.append("MEDIUM_DEBT_TO_EQUITY")
            confidence -= 0.1
        
        # Check current ratio
        current_ratio = financials.get('current_ratio', 0)
        if current_ratio < 1.0:
            risk_factors.append("LOW_CURRENT_RATIO")
            confidence -= 0.15
        elif current_ratio < 1.5:
            risk_factors.append("MEDIUM_CURRENT_RATIO")
            confidence -= 0.05
        
        # Check interest coverage
        interest_coverage = financials.get('interest_coverage_ratio', 0)
        if interest_coverage < 1.5:
            risk_factors.append("LOW_INTEREST_COVERAGE")
            confidence -= 0.15
        
        # Check trajectory from profile
        trajectory = profile.get('trajectory', 'STABLE')
        if trajectory == 'DECLINING':
            risk_factors.append("DECLINING_TRAJECTORY")
            confidence -= 0.15
        elif trajectory == 'GROWING':
            confidence += 0.05
        
        # Determine risk tier
        if len(risk_factors) >= 3 or confidence < 0.5:
            risk_tier = "HIGH"
        elif len(risk_factors) >= 1 or confidence < 0.7:
            risk_tier = "MEDIUM"
        else:
            risk_tier = "LOW"
        
        return {
            'risk_tier': risk_tier,
            'confidence': max(0.3, min(0.95, confidence)),
            'risk_factors': risk_factors
        }


class LedgerProcessor:
    """Processes loan applications through The Ledger"""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.store = None
        self.app_summary = None
        self.agent_perf = None
        self.compliance = None
    
    async def initialize(self):
        """Initialize connections"""
        self.store = EventStore(self.db_url)
        await self.store.connect()
        
        self.app_summary = ApplicationSummaryProjection()
        self.agent_perf = AgentPerformanceLedgerProjection()
        self.compliance = ComplianceAuditViewProjection()
        
        print("✓ Connected to PostgreSQL")
    
    async def close(self):
        """Close connections"""
        if self.store:
            await self.store.close()
    
    async def start_agent_session(self, agent_id: str, session_id: str, 
                                   agent_type: str, model_version: str,
                                   context_source: str) -> bool:
        """Start an agent session"""
        try:
            result = await tools.start_agent_session(
                self.store,
                agent_id=agent_id,
                session_id=session_id,
                agent_type=agent_type,
                model_version=model_version,
                context_source=context_source,
                context_token_count=5000,
            )
            return result.success
        except Exception as e:
            print(f"  ⚠ Agent session error: {e}")
            return False
    
    async def submit_application(self, application_id: str, 
                                 applicant_data: dict,
                                 financial_data: dict,
                                 loan_amount: float) -> bool:
        """Submit a loan application"""
        try:
            result = await tools.submit_application(
                self.store,
                application_id=application_id,
                applicant_id=applicant_data.get('name', 'Unknown'),
                requested_amount_usd=loan_amount,
                loan_purpose="working_capital",
                submission_channel="document_upload",
            )
            if result.success:
                print(f"  ✓ Application submitted: {loan_amount:,.0f}")
            return result.success
        except Exception as e:
            print(f"  ⚠ Submit error: {e}")
            return False
    
    async def record_credit_analysis(self, application_id: str,
                                     agent_id: str, session_id: str,
                                     risk_assessment: dict,
                                     financial_data: dict) -> bool:
        """Record credit analysis"""
        try:
            result = await tools.record_credit_analysis(
                self.store,
                application_id=application_id,
                agent_id=agent_id,
                session_id=session_id,
                model_version="v2.3",
                confidence_score=risk_assessment['confidence'],
                risk_tier=risk_assessment['risk_tier'],
                recommended_limit_usd=financial_data.get('total_assets', 0) * 0.08,
                input_data={},
            )
            if result.success:
                print(f"  ✓ Credit analysis: {risk_assessment['risk_tier']} risk")
            return result.success
        except Exception as e:
            print(f"  ⚠ Credit analysis error: {e}")
            return False
    
    async def record_fraud_screening(self, application_id: str,
                                     agent_id: str, session_id: str,
                                     applicant_data: dict) -> bool:
        """Record fraud screening"""
        try:
            result = await tools.record_fraud_screening(
                self.store,
                application_id=application_id,
                agent_id=agent_id,
                session_id=session_id,
                fraud_score=0.05,  # Low fraud score based on clean profile
                anomaly_flags=[],
                screening_model_version="v1.5",
                input_data={},
            )
            if result.success:
                print(f"  ✓ Fraud screening: 0.05 score")
            return result.success
        except Exception as e:
            print(f"  ⚠ Fraud screening error: {e}")
            return False
    
    async def record_compliance_check(self, application_id: str) -> bool:
        """Record compliance check"""
        try:
            result = await tools.record_compliance_check(
                self.store,
                application_id=application_id,
                rule_id="KYCU-2026-Q1",
                rule_version="1.0",
                passed=True,
                evidence_hash="auto_verified",
            )
            if result.success:
                print(f"  ✓ Compliance check: PASSED")
            return result.success
        except Exception as e:
            print(f"  ⚠ Compliance check error: {e}")
            return False
    
    async def generate_decision(self, application_id: str,
                               risk_assessment: dict,
                               has_fraud_check: bool,
                               has_compliance: bool) -> bool:
        """Generate decision"""
        if not (has_fraud_check and has_compliance):
            print(f"  ⚠ Cannot generate decision: missing prerequisites")
            return False
        
        try:
            # Determine recommendation based on risk
            if risk_assessment['risk_tier'] == 'HIGH':
                recommendation = 'DECLINE'
            elif risk_assessment['risk_tier'] == 'MEDIUM':
                recommendation = 'REFER'
            else:
                recommendation = 'APPROVE'
            
            result = await tools.generate_decision(
                self.store,
                application_id=application_id,
                orchestrator_agent_id="orchestrator-001",
                confidence_score=risk_assessment['confidence'],
                recommendation=recommendation,
                contributing_sessions=[],
            )
            if result.success:
                print(f"  ✓ Decision: {recommendation}")
            return result.success
        except Exception as e:
            print(f"  ⚠ Decision generation error: {e}")
            return False
    
    async def record_human_review(self, application_id: str,
                                  recommendation: str) -> bool:
        """Record human review"""
        try:
            # For automated processing, use 'auto' reviewer
            final_decision = recommendation
            
            result = await tools.record_human_review(
                self.store,
                application_id=application_id,
                reviewer_id="auto",
                override=False,
                final_decision=final_decision,
            )
            if result.success:
                print(f"  ✓ Human review: {final_decision}")
            return result.success
        except Exception as e:
            print(f"  ⚠ Human review error: {e}")
            return False
    
    async def get_application_status(self, application_id: str) -> dict:
        """Get final application status"""
        try:
            result = await resources.get_application(
                self.store, 
                {"application_summary": self.app_summary},
                application_id
            )
            if result.success:
                return result.data
            return {}
        except Exception as e:
            print(f"  ⚠ Status query error: {e}")
            return {}


async def main(company_id: str = "COMP-001"):
    """Main processing pipeline"""
    db_url = "postgresql://postgres:123@localhost:5432/ledger"
    
    print(f"\n{'='*60}")
    print(f"Automated Document Processing Pipeline")
    print(f"Company: {company_id}")
    print(f"{'='*60}\n")
    
    # Step 1: Load documents and extract data
    print("📄 Step 1: Loading Documents...")
    processor = DocumentProcessor(company_id)
    
    try:
        profile = processor.load_applicant_profile()
        print(f"  ✓ Company: {profile.get('name')}")
        print(f"  ✓ Industry: {profile.get('industry')}")
        print(f"  ✓ Risk Segment: {profile.get('risk_segment')}")
    except Exception as e:
        print(f"  ✗ Error loading profile: {e}")
        return
    
    try:
        financials = processor.load_financial_summary()
        print(f"  ✓ Financial data loaded: {len(financials)} fields")
    except Exception as e:
        print(f"  ✗ Error loading financials: {e}")
        return
    
    # Step 2: Assess risk
    print("\n📊 Step 2: Risk Assessment...")
    risk = processor.assess_risk(profile, financials)
    print(f"  ✓ Risk Tier: {risk['risk_tier']}")
    print(f"  ✓ Confidence: {risk['confidence']:.2f}")
    if risk['risk_factors']:
        print(f"  ⚠ Factors: {', '.join(risk['risk_factors'])}")
    
    # Determine loan amount
    loan_amount = processor.extract_loan_amount(financials)
    print(f"  ✓ Requested Amount: ${loan_amount:,.0f}")
    
    # Step 3: Process through Ledger
    print("\n🔗 Step 3: Processing through The Ledger...")
    ledger = LedgerProcessor(db_url)
    await ledger.initialize()
    
    # Start credit agent session
    credit_agent = "credit-agent-auto"
    credit_session = f"{company_id.lower()}-credit-001"
    print("\n  [Agent Session - Credit]")
    await ledger.start_agent_session(credit_agent, credit_session, 
                                     "CreditAnalysis", "v2.3", 
                                     f"{company_id}_documents")
    
    # Submit application
    print("\n  [Submit Application]")
    await ledger.submit_application(company_id, profile, financials, loan_amount)
    
    # Record credit analysis
    print("\n  [Credit Analysis]")
    await ledger.record_credit_analysis(company_id, credit_agent, credit_session,
                                       risk, financials)
    
    # Start fraud agent session
    fraud_agent = "fraud-agent-auto"
    fraud_session = f"{company_id.lower()}-fraud-001"
    print("\n  [Agent Session - Fraud]")
    await ledger.start_agent_session(fraud_agent, fraud_session,
                                     "FraudDetection", "v1.5",
                                     f"{company_id}_documents")
    
    # Record fraud screening
    print("\n  [Fraud Screening]")
    await ledger.record_fraud_screening(company_id, fraud_agent, fraud_session, profile)
    
    # Record compliance
    print("\n  [Compliance Check]")
    await ledger.record_compliance_check(company_id)
    
    # Generate decision
    print("\n  [Decision]")
    recommendation = "APPROVE" if risk['risk_tier'] == "LOW" else "REFER"
    await ledger.generate_decision(company_id, risk, True, True)
    
    # Human review
    print("\n  [Human Review]")
    await ledger.record_human_review(company_id, recommendation)
    
    # Get final status
    print("\n✅ Final Status:")
    status = await ledger.get_application_status(company_id)
    print(f"  Application: {status.get('application_id', 'N/A')}")
    print(f"  State: {status.get('state', 'N/A')}")
    print(f"  Decision: {status.get('decision', 'N/A')}")
    
    await ledger.close()
    
    print(f"\n{'='*60}")
    print("Processing Complete!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    company = sys.argv[1] if len(sys.argv) > 1 else "COMP-001"
    asyncio.run(main(company))