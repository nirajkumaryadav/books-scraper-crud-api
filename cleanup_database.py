import asyncio
import os
import json
from database import connect_to_mongo, get_collection, close_mongo_connection

async def complete_cleanup():
    """🧹 Complete database and file cleanup"""
    print("🧹 Starting complete cleanup...")
    
    # Connect to database
    await connect_to_mongo()
    
    try:
        # 1. Clean MongoDB
        collection = get_collection()
        result = await collection.delete_many({})
        print(f"✅ Deleted {result.deleted_count} records from MongoDB")
        
        # 2. Clean JSON file
        if os.path.exists('books_data.json'):
            os.remove('books_data.json')
            print("✅ Deleted books_data.json")
        
        # 3. Clean CSV file  
        if os.path.exists('books_data.csv'):
            os.remove('books_data.csv')
            print("✅ Deleted books_data.csv")
        
        print("🎉 Complete cleanup finished!")
        print("📝 Database is now empty and ready for fresh scraping")
        
    except Exception as e:
        print(f"❌ Cleanup error: {e}")
    
    finally:
        await close_mongo_connection()

if __name__ == "__main__":
    asyncio.run(complete_cleanup())