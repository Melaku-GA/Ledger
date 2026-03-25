import asyncio
import asyncpg
import json

async def get_events():
    conn = await asyncpg.connect('postgresql://postgres:123@localhost:5432/ledger')
    
    events = await conn.fetch('''
        SELECT event_id, stream_id, stream_position, event_type, event_version, payload, recorded_at 
        FROM events 
        ORDER BY stream_id, stream_position
    ''')
    
    print(f'Total events: {len(events)}')
    print()
    
    for e in events:
        print(f'Stream: {e["stream_id"]}')
        print(f'  Position: {e["stream_position"]}')
        print(f'  Type: {e["event_type"]}')
        print(f'  Version: {e["event_version"]}')
        payload = e['payload']
        if isinstance(payload, dict):
            # Pretty print payload
            print(f'  Payload: {json.dumps(payload, indent=4)}')
        print()
    
    await conn.close()

asyncio.run(get_events())