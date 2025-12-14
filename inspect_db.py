import asyncio
from database import db
import logging

# Configure logger to print to stdout
logging.basicConfig(level=logging.INFO)

async def main():
    if not db.client:
        print("No Supabase client.")
        return

    try:
        # Fetch one record to see columns
        res = await db._run_async(lambda: db.client.table("instalacoes").select("*").limit(1).execute())
        if res.data:
            print("Columns:", res.data[0].keys())
            print("Sample:", res.data[0])
        else:
            print("Table empty or no access.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
