import asyncio
import asyncpg
import sys

async def test():
    try:
        conn = await asyncpg.connect('postgresql://postgres:123@localhost:5432/ledger')
        print('Connected to ledger database')
        
        # Check tables
        tables = await conn.fetch('''
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        ''')
        
        print('Tables in ledger database:')
        for t in tables:
            print(f'  - {t["table_name"]}')
        
        # Check events table
        if 'events' in [t['table_name'] for t in tables]:
            count = await conn.fetchval('SELECT COUNT(*) FROM events')
            print(f'Events count: {count}')
        
        # Check event_streams table  
        if 'event_streams' in [t['table_name'] for t in tables]:
            streams = await conn.fetchval('SELECT COUNT(*) FROM event_streams')
            print(f'Streams count: {streams}')
        
        await conn.close()
    except Exception as e:
        print(f'Error: {e}')

asyncio.run(test())