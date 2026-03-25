import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect('postgresql://postgres:123@localhost:5432/ledger')
    
    # Check for any COMP-001 related streams
    streams = await conn.fetch('''
        SELECT stream_id, aggregate_type, current_version
        FROM event_streams 
        WHERE stream_id LIKE '%COMP-001%' OR stream_id LIKE '%comp001%'
    ''')
    
    print('COMP-001 related streams:')
    print(f'  Count: {len(streams)}')
    for s in streams:
        print(f'  {s["stream_id"]}: {s["current_version"]}')
    
    # Check events
    events = await conn.fetch('''
        SELECT stream_id, stream_position, event_type
        FROM events 
        WHERE stream_id LIKE '%COMP-001%' OR stream_id LIKE '%comp001%'
        ORDER BY stream_id, stream_position
    ''')
    
    print()
    print('COMP-001 related events:')
    print(f'  Count: {len(events)}')
    for e in events:
        print(f'  {e["stream_id"]} @ {e["stream_position"]}: {e["event_type"]}')
    
    await conn.close()

asyncio.run(check())