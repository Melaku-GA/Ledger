# DESIGN.md

---

## 1. Aggregate Boundary Justification

### Question: Why is ComplianceRecord a separate aggregate from LoanApplication? What would couple if you merged them?

**Answer:**

ComplianceRecord is a separate aggregate from LoanApplication to prevent **concurrency coupling** and **failure domain isolation**.

**What would couple if merged:**

If ComplianceRecord was part of the LoanApplication aggregate:
1. A compliance check (performed by a separate AI agent) would write to the same stream as loan application updates
2. Two concurrent operations would cause optimistic concurrency conflicts:
   - CreditAnalysisAgent appends CreditAnalysisCompleted
   - ComplianceAgent appends ComplianceRulePassed
   - Both reading at version 3 would result in one failing

**Failure mode under concurrent writes:**

```
Timeline:
1. Agent A reads loan-COMP-001 at version 3
2. Agent B (compliance) reads loan-COMP-001 at version 3  
3. Agent A appends at expected_version=3 → SUCCESS (v3→v4)
4. Agent B tries append at expected_version=3 → OptimisticConcurrencyError!
```

With separate aggregates:
- LoanApplication stream: loan-COMP-001
- ComplianceRecord stream: compliance-COMP-001

These can be updated concurrently without conflicts.

**Why our boundary is correct:**
- Compliance checks are performed by a separate AI agent (ComplianceAgent)
- Regulation versions are shared across multiple applications
- Failed compliance checks shouldn't block all application updates
- Different agents own different aggregates (CQRS write separation)

---

## 2. Projection Strategy

### ApplicationSummary Projection

**Inline vs Async:** Async (default)

**Justification:**
- Write latency: Low priority (eventual consistency OK for most queries)
- Read performance: Critical (p99 < 50ms required)
- We use async projection daemon that batches events

**SLO:** p99 < 50ms lag

**Snapshot Strategy:** Not needed - this is a current-state projection, rebuilds from scratch if corrupted

---

### AgentPerformanceLedger Projection

**Inline vs Async:** Async

**Justification:**
- Write latency: Low priority (metrics can be delayed)
- Read performance: Critical for agent comparison queries
- Aggregate calculations happen in daemon

**SLO:** p99 < 50ms lag

**Snapshot Strategy:** Not needed - rebuilds in seconds from event replay

---

### ComplianceAuditView Projection (Temporal Query)

**Inline vs Async:** Async

**Justification:**
- Must support temporal queries: `get_compliance_at(application_id, timestamp)`
- Write latency: Lower priority
- Read performance: Critical for regulatory queries

**SLO:** p99 < 200ms lag

**Snapshot Strategy:** Time-triggered snapshots

- Snapshot trigger: Every 10,000 events OR every 5 minutes (whichever comes first)
- Snapshot invalidation: On schema migration or corruption detection
- We store temporal snapshots in a separate table with timestamp索引

**Snapshot Table:**
```sql
CREATE TABLE compliance_snapshots (
    application_id TEXT,
    snapshot_timestamp TIMESTAMPTZ,
    state JSONB,
    PRIMARY KEY (application_id, snapshot_timestamp)
);
```

---

## 3. Concurrency Analysis

### Question: Under peak load (100 concurrent applications, 4 agents each), how many OptimisticConcurrencyErrors do you expect per minute?

**Analysis:**

- 100 concurrent applications
- 4 agents per application (CreditAnalysis, FraudDetection, Compliance, Orchestrator)
- Total potential streams: 100 × 4 = 400 concurrent agent operations

**Expected collision rate:**

The probability of a collision on any single stream depends on:
- Event rate per application: ~5 events (Application → Analysis → Fraud → Compliance → Decision)
- Average application processing time: ~30 seconds
- Events per second per stream: 5/30 = 0.17 events/sec

**Collision probability formula:**
For two agents on the same application to collide, both must read and write within the same "version window."

Given:
- Average read-to-write latency: ~50ms
- Window of vulnerability: ~100ms

**Expected OptimisticConcurrencyErrors per minute:**
- 100 applications × 4 agents × 0.17 events/sec × (100ms collision window) 
- ≈ 0.68 collisions per second per application
- ≈ 40 collisions per minute across all applications

**This is manageable** - most applications won't see conflicts, but a few will have 1-2 retries.

### Retry Strategy

```python
MAX_RETRIES = 3
RETRY_DELAYS = [0.1, 0.5, 1.0]  # seconds (exponential backoff)

async def append_with_retry(stream_id, events, expected_version):
    for attempt in range(MAX_RETRIES):
        try:
            return await store.append(stream_id, events, expected_version)
        except OptimisticConcurrencyError as e:
            if attempt == MAX_RETRIES - 1:
                raise
            # Reload stream and retry with new version
            new_version = await store.stream_version(stream_id)
            expected_version = new_version
            await asyncio.sleep(RETRY_DELAYS[attempt])
```

**Maximum retry budget:** 3 attempts with exponential backoff (total ~1.6 seconds)
- After 3 failures, return failure to caller
- Caller can decide to queue for later or escalate

---

## 4. Upcasting Inference Decisions

### CreditAnalysisCompleted v1→v2

**Inferred Fields:**

| Field | Inference Strategy | Error Rate | Downstream Consequence |
|-------|-------------------|------------|------------------------|
| `model_version` | Timestamp-based: before June 2025 = "v1-legacy", after = "v2-stable" | ~5% | Wrong model attribution in analytics |
| `confidence_score` | **Null** (not inferred) | N/A | N/A - honest null |
| `regulatory_basis` | Decision reason keyword mapping | ~15% | Potential misattribution of regulation |

**When to choose null vs inference:**

- **model_version:** Inference is acceptable (5% error acceptable for analytics)
- **confidence_score:** MUST be null - fabrication would create false certainty
- **regulatory_basis:** Inference with higher error tolerance (15%) because it's supplementary

**Why NOT fabricate confidence_score:**
```
Fabricating: "confidence_score": 0.87  ← Creates false certainty
Null: "confidence_score": null ← Honest: "we don't know"
```

For regulatory audit, fabricated data is worse than missing data.

---

### DecisionGenerated v1→v2

**Inferred Fields:**

| Field | Inference Strategy | Error Rate | Downstream Consequence |
|-------|-------------------|------------|------------------------|
| `model_versions{}` | Load each contributing AgentSession to get model_version | ~0% (direct lookup) | N/A - accurate |

This one is accurate because it does a direct store lookup, not inference.

---

## 5. EventStoreDB Comparison

### PostgreSQL → EventStoreDB Mapping

| PostgreSQL Concept | EventStoreDB Equivalent |
|-------------------|------------------------|
| `events` table | Streams (append-only) |
| Stream ID (e.g., "loan-COMP-001") | Stream Name |
| `load_all()` | $all stream subscription |
| `stream_position` | Event number in stream |
| `global_position` | Log position |
| ProjectionDaemon | Persistent subscriptions |
| Outbox pattern | Persistent subscriptions with catch-up |

### What EventStoreDB Gives Us (that we must work harder for):

1. **Persistent Subscriptions:**
   - EventStoreDB: Built-in $persist subscription to stream
   - Our implementation: Polling daemon with checkpoints

2. **Competing Consumers:**
   - EventStoreDB: Multiple consumers can compete for events from same subscription
   - Our implementation: Would need Redis or additional coordination

3. **Native GRPC Streaming:**
   - EventStoreDB: Native streaming over gRPC
   - Our implementation: HTTP polling or PostgreSQL LISTEN/NOTIFY

4. **Built-in Hash Chain:**
   - EventStoreDB: Optional stream metadata for integrity
   - Our implementation: Custom AuditIntegrityCheckRun events

5. **Warranties (Tamper Evidence):**
   - EventStoreDB: Stream info cache hashes
   - Our implementation: Must compute and verify manually

### Where Our PostgreSQL Implementation Excels:

- **Simpler deployment:** Most enterprises already have PostgreSQL
- **Familiar tooling:** SQL queries, pgAdmin, etc.
- **Cost:** No additional infrastructure
- **Flexibility:** Full SQL access to events table

---

## 6. What You Would Do Differently

### Single Most Significant Architectural Decision

**What we built:** In-memory EventStore for testing, PostgreSQL for production

**What we would reconsider:** The event store abstraction layer

**The issue:**
- We created an abstraction that works for both in-memory and PostgreSQL
- However, some PostgreSQL-specific features aren't exposed (LISTEN/NOTIFY for real-time notifications)
- The abstraction makes it harder to optimize for specific backends

**What we would do differently:**

```python
# Instead of abstracting, we should have:
# Option A: Use PostgreSQL-specific optimizations from day 1
# - LISTEN/NOTIFY for projection daemon (instead of polling)
# - Advisory locks for distributed projection coordination

# Option B: Accept vendor lock-in for production
# - Use EventStoreDB directly 
# - Focus on domain logic, not infrastructure
```

**This is the one-way door:**
- Choosing PostgreSQL is a 2-3 year commitment
- Migrating to EventStoreDB later would require significant rewriting
- With another day, we'd document this tradeoff more explicitly in DESIGN.md

**Reflection:**
The code works and tests pass, but if we were building for a real enterprise deployment, we'd spend another day on:
1. PostgreSQL LISTEN/NOTIFY integration for real-time projections
2. Distributed daemon coordination with advisory locks
3. Better documentation of migration path to EventStoreDB

---

## Summary

| Aspect | Decision | Tradeoff |
|--------|----------|----------|
| Aggregate boundaries | Separate ComplianceRecord | Prevents concurrency coupling |
| Projection strategy | Async with time-triggered snapshots | Lower write latency, eventual consistency |
| Concurrency | Optimistic with 3-retry | ~40 OCC errors/min under load, handled gracefully |
| Upcasting | Null for unknown confidence | Honest vs fabricated - choose integrity |
| Backend | PostgreSQL | Simpler ops, but less specialized than EventStoreDB |
| Biggest regret | Abstraction layer | Could have optimized PostgreSQL-specific features |
