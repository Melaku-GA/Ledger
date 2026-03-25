import asyncio
import asyncpg

async def get_full_event():
    conn = await asyncpg.connect('postgresql://postgres:123@localhost:5432/ledger')
    
    # Get the ApplicationSubmitted event
    event = await conn.fetchrow('''
        SELECT event_id, stream_id, stream_position, event_type, event_version, payload, metadata, recorded_at 
        FROM events 
        WHERE event_type = 'ApplicationSubmitted'
        LIMIT 1
    ''')
    
    print('=== Full Event Details ===')
    print(f'Event ID: {event["event_id"]}')
    print(f'Stream ID: {event["stream_id"]}')
    print(f'Stream Position: {event["stream_position"]}')
    print(f'Event Type: {event["event_type"]}')
    print(f'Event Version: {event["event_version"]}')
    print(f'Recorded At: {event["recorded_at"]}')
    print()
    print('Payload:')
    print(event['payload'])
    print()
    print('Metadata:')
    print(event['metadata'])
    
    await conn.close()

asyncio.run(get_full_event())