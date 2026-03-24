# Video Demo Guide - The Ledger

This guide shows how to demonstrate the Week Standard requirements for the video submission.

## Prerequisites
```bash
cd starter
pip install -r requirements.txt
```

---

## Step 1: The Week Standard - Complete Decision History

**Run the demo script that shows full decision history:**
```bash
python demo.py
```

**Expected output shows:**
- Application Submitted
- Credit Analysis Complete (risk_tier=LOW)
- Fraud Screening Complete (score=0.1)
- Compliance Check Passed
- Decision Generated: APPROVE
- Human Review Complete
- Application Approved!

**Query complete history via MCP:**
```bash
python -c "
import asyncio
from src.mcp.server import handle_tool_call, handle_resource_call

async def test():
    # Run full lifecycle
    await handle_tool_call('start_agent_session', {'agent_id': 'a', 'session_id': 's1', 'agent_type': 'Credit', 'model_version': 'v1', 'context_source': 'x', 'context_token_count': 1000})
    await handle_tool_call('submit_application', {'application_id': 'X', 'applicant_id': 'Acme', 'requested_amount_usd': 100000, 'loan_purpose': 'Test'})
    await handle_tool_call('record_credit_analysis', {'application_id': 'X', 'agent_id': 'a', 'session_id': 's1', 'model_version': 'v1', 'confidence_score': 0.85, 'risk_tier': 'LOW', 'recommended_limit_usd': 100000, 'input_data': {}})
    
    # Query audit trail
    result = await handle_resource_call('ledger://applications/X/audit-trail')
    print(f'Events: {len(result.data.get(\"events\", []))}')
    for e in result.data.get('events', []):
        print(f'  {e[\"stream_position\"]}: {e[\"event_type\"]}')

asyncio.run(test())
"
```

---

## Step 2: Concurrency Under Pressure - Double Decision Test

**Run the concurrency test:**
```bash
python -m pytest tests/test_concurrency.py -v
```

**Shows:**
- Two agents both try to append to same stream
- One succeeds, one gets OptimisticConcurrencyError
- Exactly one event appended (not two)

**Code to demonstrate race condition:**
```bash
python -c "
import asyncio
from ledger.event_store import InMemoryEventStore, OptimisticConcurrencyError

async def race():
    store = InMemoryEventStore()
    await store.append('loan-X', [{'event_type': 'A'}], -1)
    await store.append('loan-X', [{'event_type': 'B'}], 0)
    
    async def agent(name):
        try:
            pos = await store.append('loan-X', [{'event_type': name}], 1)
            print(f'{name} WON at position {pos}')
        except OptimisticConcurrencyError as e:
            print(f'{name} LOST - got OCC error')
    
    await asyncio.gather(agent('AgentA'), agent('AgentB'))
    print(f'Final version: {await store.stream_version(\"loan-X\")}')

asyncio.run(race())
"
```

---

## Step 3: Temporal Compliance Query

**Query compliance at a past timestamp:**
```python
python -c "
import asyncio
from src.mcp.server import handle_tool_call, handle_resource_call

async def demo():
    # Run compliance check
    await handle_tool_call('start_agent_session', {'agent_id': 'a', 'session_id': 's1', 'agent_type': 'Credit', 'model_version': 'v1', 'context_source': 'x', 'context_token_count': 1000})
    await handle_tool_call('submit_application', {'application_id': 'COMP-001', 'applicant_id': 'Acme', 'requested_amount_usd': 100000, 'loan_purpose': 'Test'})
    await handle_tool_call('record_compliance_check', {'application_id': 'COMP-001', 'rule_id': 'KYB', 'rule_version': '2026-Q1', 'passed': True})
    
    # Current compliance
    result = await handle_resource_call('ledger://applications/COMP-001/compliance')
    print(f'Current: {result.data}')
    
    # Query at past time (temporal query)
    result = await handle_resource_call('ledger://applications/COMP-001/compliance?as_of=2024-01-01T00:00:00')
    print(f'As of 2024: {result.data}')

asyncio.run(demo())
"
```

---

## Step 4: Upcasting & Immutability

**Show v1 events are upcasted to v2 without modifying stored data:**
```bash
python -m pytest tests/phase4/test_upcasting.py::test_stored_events_immutable -v
```

**Code demonstrating upcasting:**
```python
python -c "
import asyncio
from ledger.event_store import InMemoryEventStore
from src.upcasting.registry import UpcasterRegistry

async def demo():
    store = InMemoryEventStore()
    registry = UpcasterRegistry()
    
    # Append v1 event
    await store.append('loan-X', [{'event_type': 'CreditAnalysisCompleted', 'event_version': 1, 'payload': {'risk_tier': 'LOW'}}], -1)
    
    # Load through store (should be upcasted)
    events = await store.load_stream('loan-X')
    print(f'Loaded event version: {events[0][\"event_version\"]}')
    print(f'Payload has model_version: {\"model_version\" in events[0][\"payload\"]}')

asyncio.run(demo())
"
```

---

## Step 5: Gas Town Recovery

**Simulate agent crash and recovery:**
```bash
python -m pytest tests/test_gas_town.py -v
```

**Manual demonstration:**
```python
python -c "
import asyncio
from src.integrity.gas_town import reconstruct_agent_context
from ledger.event_store import InMemoryEventStore

async def demo():
    store = InMemoryEventStore()
    
    # Agent starts session
    await store.append('agent-credit-s1', [{'event_type': 'AgentContextLoaded', 'event_version': 1, 'payload': {'agent_id': 'credit', 'session_id': 's1', 'model_version': 'v1'}}], -1)
    
    # Agent does work
    await store.append('agent-credit-s1', [{'event_type': 'CreditAnalysisCompleted', 'event_version': 2, 'payload': {'application_id': 'APP-1'}}], 0)
    
    # Simulate crash - reconstruct context
    context = await reconstruct_agent_context(store, 'credit', 's1')
    print(f'Context text: {context.context_text[:100]}...')
    print(f'Last position: {context.last_event_position}')
    print(f'Can resume: {context.session_health_status}')

asyncio.run(demo())
"
```

---

## Quick Test Summary (Run All)

```bash
# All core tests
cd starter

# 1. Week standard
python demo.py

# 2. Concurrency
python -m pytest tests/test_concurrency.py -v

# 3. Projections
python -m pytest tests/phase3/test_projections.py -v

# 4. Upcasting
python -m pytest tests/phase4/test_upcasting.py -v

# 5. MCP lifecycle
python -m pytest tests/test_mcp_lifecycle.py -v
```

Expected: All tests pass!
