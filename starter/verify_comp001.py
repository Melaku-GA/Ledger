import asyncio
import asyncpg

async def verify():
    conn = await asyncpg.connect('postgresql://postgres:123@localhost:5432/ledger')
    
    # Get COMP-001 events
    events = await conn.fetch('''
        SELECT stream_position, event_type, event_version, payload, recorded_at
        FROM events 
        WHERE stream_id = 'loan-COMP-001'
        ORDER BY stream_position
    ''')
    
    print('=== COMP-001 Events in PostgreSQL ===')
    print(f'Total events: {len(events)}\n')
    
    for e in events:
        print(f'Position {e["stream_position"]}: {e["event_type"]} (v{e["event_version"]})')
        print(f'  Payload: {e["payload"]}')
        print(f'  Recorded: {e["recorded_at"]}')
        print()
    
    await conn.close()

asyncio.run(verify())