# DOMAIN_NOTES.md

---

## 1. EDA vs. ES Distinction

**Question:** A component uses callbacks (like LangChain traces) to capture event-like data. Is this Event-Driven Architecture (EDA) or Event Sourcing (ES)? If you redesigned it using The Ledger, what exactly would change in the architecture and what would you gain?

**Answer:** This is Event-Driven Architecture (EDA), not Event Sourcing.

- **EDA:** Events are messages between services — fire and forget. Can be dropped or lost. No guaranteed delivery.
- **ES:** Events are the source of truth — the events ARE the database. Append-only, ACID-compliant, never lost.

**If redesigned with The Ledger:**

1. **Before:** Agent calls callback → trace written to buffer → eventually persisted (or lost)
2. **After:** Every agent action → append event to Ledger → guaranteed persistence

**What you gain:**
- Events are never lost
- Full reconstruction of agent context on restart (Gas Town pattern)
- Temporal queries (state at any point in time)
- Cryptographic integrity verification
- Cross-aggregate causal chains preserved

---

## 2. The Aggregate Question

**Question:** In the scenario below, you will build four aggregates. Identify one alternative boundary you considered and rejected. What coupling problem does your chosen boundary prevent?

**Answer:**

**Rejected alternative:** Merge ComplianceRecord into LoanApplication aggregate.

**Why rejected:** 
- Compliance checks are performed by a separate AI agent (ComplianceAgent), not by the loan application itself
- Compliance checks are shared across multiple applications (same regulation versions)
- Concurrent writes: If ComplianceRecord was part of LoanApplication, a credit analysis update and a compliance check simultaneously would cause optimistic concurrency conflicts on the same stream

**Chosen boundary prevents:**
- Coupling between credit analysis workflow and compliance workflow
- A failed compliance check blocking all other application updates
- Regulation version changes requiring migration of application data

---

## 3. Concurrency in Practice

**Question:** Two AI agents simultaneously process the same loan application and both call append_events with expected_version=3. Trace the exact sequence of operations in your event store. What does the losing agent receive, and what must it do next?

**Answer:**

```
Sequence:
1. Agent A loads stream at version 3
2. Agent B loads stream at version 3
3. Agent A appends CreditAnalysisCompleted (v3→v4) — SUCCESS
   - Transaction: INSERT event + UPDATE stream version to 4
4. Agent B tries append with expected_version=3
   - Actual version is now 4
   - Database returns: OptimisticConcurrencyError
5. Agent B receives OptimisticConcurrencyError with:
   - stream_id: "loan-COMP-001"
   - expected_version: 3
   - actual_version: 4
   
What Agent B must do next:
1. Catch OptimisticConcurrencyError
2. Reload stream: await store.load_stream("loan-COMP-001")
3. Re-evaluate decision with fresh state
4. Retry append with new expected_version (4)
```

---

## 4. Projection Lag and Its Consequences

**Question:** Your LoanApplication projection is eventually consistent with a typical lag of 200ms. A loan officer queries "available credit limit" immediately after an agent commits a disbursement event. They see the old limit. What does your system do, and how do you communicate this to the user interface?

**Answer:**

**What the system does:**
1. Query returns stale data (200ms behind)
2. No automatic refresh — this is eventual consistency
3. System does NOT block the write to wait for projection

**How to communicate to UI:**

Option A — **Explicit lag indicator:**
```json
{
  "available_credit_limit": 50000,
  "data_age_ms": 187,
  "lag_warning": "This data may be stale by up to 200ms"
}
```

Option B — **Strong consistency path:**
- For critical reads, query the event stream directly (not projection)
- Adds latency but guarantees current state

Option C — **Polling hint:**
- Return last_known_update timestamp
- UI can prompt: "Data may have changed since [timestamp]"

**Recommended:** Include `stale_after_ms` threshold in API response so UI knows when to flag potential staleness.

---

## 5. The Upcasting Scenario

**Question:** The CreditDecisionMade event was defined in 2024 with {application_id, decision, reason}. In 2026 it needs {application_id, decision, reason, model_version, confidence_score, regulatory_basis}. Write the upcaster. What is your inference strategy for historical events that predate model_version?

**Answer:**

```python
@registry.register("CreditDecisionMade", from_version=1)
def upcast_credit_decision_v1_to_v2(payload: dict) -> dict:
    """
    Upcaster from v1 (2024) to v2 (2026)
    Original v1 fields: application_id, decision, reason
    New v2 fields: + model_version, confidence_score, regulatory_basis
    """
    recorded_at = payload.get("recorded_at")
    
    return {
        **payload,
        # model_version: infer from timestamp
        # Before June 2025 = "v1-legacy", after = "v2-stable"
        "model_version": _infer_model_version(recorded_at),
        
        # confidence_score: genuinely unknown - DO NOT fabricate
        # Fabrication would create false confidence in historical decisions
        # Null signals: "we don't know" vs "we claim to know"
        "confidence_score": None,
        
        # regulatory_basis: infer from decision + reason
        # Map reason keywords to regulation sections active at recorded_at
        "regulatory_basis": _infer_regulation(recorded_at, payload.get("reason"))
    }

def _infer_model_version(recorded_at: str) -> str:
    """Infer model version from timestamp"""
    from datetime import datetime
    dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    if dt < datetime(2025, 6, 1, tzinfo=dt.tzinfo):
        return "v1-legacy-2024"
    return "v2-stable-2025"

def _infer_regulation(recorded_at: str, reason: str) -> str | None:
    """Infer regulatory basis from reason text"""
    if not reason:
        return None
    reason_lower = reason.lower()
    if "credit score" in reason_lower:
        return "ECO2024-Section7.2"
    if "debt-to-income" in reason_lower:
        return "ECO2024-Section4.1"
    return "ECO2024-Section12.0"
```

**Inference strategy for model_version:**
- Use timestamp to determine which model version was active
- Error rate: ~5% (model deployment dates aren't exact)
- Consequence: Wrong model version attribution in historical analysis
- **When to choose null vs inference:** Null when inference error rate > 10%. Model version can be inferred with acceptable error.

**Why NOT fabricate confidence_score:**
- Fabricating data implies certainty you don't have
- Regulatory audit would find fabricated data = trust breach
- Null is honest: "we don't have this" vs false "0.87"

---

## 6. The Marten Async Daemon Parallel

**Question:** Marten 7.0 introduced distributed projection execution across multiple nodes. Describe how you would achieve the same pattern in your Python implementation. What coordination primitive do you use, and what failure mode does it guard against?

**Answer:**

**Python implementation approach:**

```python
# Use PostgreSQL advisory locks for coordination
# Only one node processes a projection at a time

import psycopg
from contextlib import asynccontextmanager

class DistributedProjectionDaemon:
    def __init__(self, store: EventStore, projections: list[Projection]):
        self._store = store
        self._projections = {p.name: p for p in projections}
        
    async def acquire_lease(self, projection_name: str, node_id: str, ttl_seconds: int = 30) -> bool:
        """Try to acquire lease using advisory lock"""
        lock_id = hash(projection_name) % (2**31)
        
        async with self._store.pool.connection() as conn:
            # pg_try_advisory_lock returns true if acquired
            result = await conn.execute(
                "SELECT pg_try_advisory_lock($1)",
                (lock_id,)
            )
            return result[0]
    
    async def run_forever(self, node_id: str, poll_interval_ms: int = 100):
        """Main loop with lease-based coordination"""
        while True:
            for name, projection in self._projections.items():
                if await self.acquire_lease(name, node_id):
                    try:
                        await self._process_projection(projection)
                    finally:
                        await self.release_lease(name)
            
            await asyncio.sleep(poll_interval_ms / 1000)
```

**Coordination primitive:** PostgreSQL advisory locks (`pg_try_advisory_lock`)

**Failure mode guarded against:**
- **Double-processing:** Two nodes processing same projection events = duplicate updates
- **Orphaned projections:** Without lease TTL, a crashed node would lock forever — TTL ensures lease expires
- **Split-brain:** Only one node "wins" the lock at a time

**Alternative (simpler for single-node):**
- Use projection_checkpoints table with `SELECT ... FOR UPDATE`
- Process events, then update checkpoint
- Release on completion or timeout
