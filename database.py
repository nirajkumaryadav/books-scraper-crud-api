import motor.motor_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from typing import List, Dict
import json
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB connection settings
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = "books_scraper_db"
COLLECTION_NAME = "books"

# Fallback storage for when MongoDB is not available
_memory_storage: List[Dict] = []
_use_memory_storage = False

class Database:
    client: AsyncIOMotorClient = None
    database = None

database = Database()

async def get_database() -> AsyncIOMotorClient:
    """Get database client"""
    return database.client

async def connect_to_mongo():
    """Create database connection with graceful fallback"""
    global _use_memory_storage
    
    try:
        logger.info("🔌 Attempting to connect to MongoDB...")
        database.client = motor.motor_asyncio.AsyncIOMotorClient(
            MONGODB_URL, 
            serverSelectionTimeoutMS=3000  # 3 second timeout
        )
        database.database = database.client[DATABASE_NAME]
        
        # Test the connection
        await database.client.admin.command('ping')
        logger.info(f"✅ Connected to MongoDB at {MONGODB_URL}")
        logger.info(f"📊 Using database: {DATABASE_NAME}")
        _use_memory_storage = False
        
        # Create indexes
        await create_indexes()
        
    except Exception as e:
        logger.warning(f"⚠️ MongoDB connection failed: {e}")
        logger.info("🔄 Falling back to in-memory storage")
        logger.info("💡 To use MongoDB: Start MongoDB service with 'net start MongoDB'")
        _use_memory_storage = True
        
        # Load existing data if available
        await _load_memory_data()

async def _load_memory_data():
    """Load existing data into memory storage"""
    global _memory_storage
    try:
        with open('books_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'books' in data:
                _memory_storage.extend(data['books'])
            elif isinstance(data, list):
                _memory_storage.extend(data)
        logger.info(f"📁 Loaded {len(_memory_storage)} books from file")
    except FileNotFoundError:
        logger.info("📝 Starting with empty storage")
        _memory_storage = []

async def close_mongo_connection():
    """Close database connection and save memory data if needed"""
    global _memory_storage
    
    if _use_memory_storage and _memory_storage:
        # Save memory data to file
        try:
            with open('books_data.json', 'w', encoding='utf-8') as f:
                json.dump({
                    "metadata": {
                        "saved_at": datetime.now().isoformat(),
                        "total_books": len(_memory_storage),
                        "storage_type": "in-memory"
                    },
                    "books": _memory_storage
                }, f, indent=2)
            logger.info(f"💾 Saved {len(_memory_storage)} books to file")
        except Exception as e:
            logger.error(f"❌ Failed to save data: {e}")
    
    if database.client:
        database.client.close()
        logger.info("📝 Disconnected from database")

# Simple in-memory collection for fallback
class MemoryCollection:
    """In-memory collection simulator for when MongoDB is not available"""
    
    async def insert_one(self, document):
        document['_id'] = f"mem_{len(_memory_storage)}_{int(datetime.now().timestamp())}"
        _memory_storage.append(document.copy())
        return type('InsertResult', (), {'inserted_id': document['_id']})()
    
    async def insert_many(self, documents):
        inserted_ids = []
        for doc in documents:
            doc['_id'] = f"mem_{len(_memory_storage)}_{int(datetime.now().timestamp())}"
            _memory_storage.append(doc.copy())
            inserted_ids.append(doc['_id'])
        return type('InsertManyResult', (), {'inserted_ids': inserted_ids})()
    
    async def find_one(self, query):
        for item in _memory_storage:
            if self._match_query(item, query):
                return item
        return None
    
    def find(self, query=None):
        if query is None:
            query = {}
        results = [item for item in _memory_storage if self._match_query(item, query)]
        return MemoryCursor(results)
    
    async def update_one(self, query, update):
        for item in _memory_storage:
            if self._match_query(item, query):
                if '$set' in update:
                    item.update(update['$set'])
                return type('UpdateResult', (), {'matched_count': 1, 'modified_count': 1})()
        return type('UpdateResult', (), {'matched_count': 0, 'modified_count': 0})()
    
    async def delete_one(self, query):
        for i, item in enumerate(_memory_storage):
            if self._match_query(item, query):
                del _memory_storage[i]
                return type('DeleteResult', (), {'deleted_count': 1})()
        return type('DeleteResult', (), {'deleted_count': 0})()
    
    async def delete_many(self, query):
        if not query:  # Delete all
            count = len(_memory_storage)
            _memory_storage.clear()
            return type('DeleteResult', (), {'deleted_count': count})()
        
        deleted_count = 0
        for i in range(len(_memory_storage) - 1, -1, -1):
            if self._match_query(_memory_storage[i], query):
                del _memory_storage[i]
                deleted_count += 1
        return type('DeleteResult', (), {'deleted_count': deleted_count})()
    
    async def count_documents(self, query=None):
        if query is None:
            return len(_memory_storage)
        return len([item for item in _memory_storage if self._match_query(item, query)])
    
    def aggregate(self, pipeline):
        return MemoryAggregationCursor(_memory_storage, pipeline)
    
    def _match_query(self, item, query):
        """Simple query matching for in-memory storage"""
        for key, value in query.items():
            if key not in item:
                return False
            
            if isinstance(value, dict):
                if '$regex' in value:
                    import re
                    pattern = value['$regex']
                    flags = re.IGNORECASE if value.get('$options') == 'i' else 0
                    if not re.search(pattern, str(item[key]), flags):
                        return False
                elif '$gte' in value and item[key] < value['$gte']:
                    return False
                elif '$lte' in value and item[key] > value['$lte']:
                    return False
            elif item[key] != value:
                return False
        return True

class MemoryCursor:
    """Simple cursor for in-memory queries"""
    
    def __init__(self, data):
        self.data = data
        self._skip = 0
        self._limit = None
        self._sort_field = None
        self._sort_direction = 1
    
    def skip(self, count):
        self._skip = count
        return self
    
    def limit(self, count):
        self._limit = count
        return self
    
    def sort(self, field, direction=1):
        self._sort_field = field
        self._sort_direction = direction
        return self
    
    async def to_list(self, length=None):
        result = self.data[:]
        
        if self._sort_field:
            reverse = self._sort_direction == -1
            result.sort(key=lambda x: x.get(self._sort_field, 0), reverse=reverse)
        
        start = self._skip
        end = start + self._limit if self._limit else None
        return result[start:end]

class MemoryAggregationCursor:
    """Simple aggregation for basic statistics"""
    
    def __init__(self, data, pipeline):
        self.data = data
        self.pipeline = pipeline
    
    async def to_list(self, length=None):
        for stage in self.pipeline:
            if '$group' in stage:
                group = stage['$group']
                if group['_id'] is None:
                    # Calculate overall statistics
                    result = {}
                    if 'avg_price' in group:
                        prices = [item.get('price', 0) for item in self.data]
                        result['avg_price'] = sum(prices) / len(prices) if prices else 0
                    if 'min_price' in group:
                        prices = [item.get('price', 0) for item in self.data]
                        result['min_price'] = min(prices) if prices else 0
                    if 'max_price' in group:
                        prices = [item.get('price', 0) for item in self.data]
                        result['max_price'] = max(prices) if prices else 0
                    if 'avg_rating' in group:
                        ratings = [item.get('star_rating', 0) for item in self.data]
                        result['avg_rating'] = sum(ratings) / len(ratings) if ratings else 0
                    return [result]
                else:
                    # Group by field
                    groups = {}
                    group_field = group['_id']
                    for item in self.data:
                        key = item.get(group_field, 'Unknown')
                        groups.setdefault(key, []).append(item)
                    
                    return [{'_id': key, 'count': len(items)} for key, items in groups.items()]
        return []

def get_collection():
    """Get the books collection (MongoDB or in-memory fallback)"""
    if _use_memory_storage:
        return MemoryCollection()
    else:
        return database.database[COLLECTION_NAME]

async def create_indexes():
    """Create database indexes for better performance"""
    if _use_memory_storage:
        logger.info("📝 Using in-memory storage - no indexes needed")
        return
    
    try:
        collection = database.database[COLLECTION_NAME]
        
        # Create indexes for common query fields
        await collection.create_index("title")
        await collection.create_index("price")
        await collection.create_index("star_rating")
        await collection.create_index("availability")
        
        logger.info("✅ Database indexes created successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to create indexes: {e}")

def is_using_memory_storage():
    """Check if using in-memory storage"""
    return _use_memory_storage

def get_storage_info():
    """Get information about current storage type"""
    if _use_memory_storage:
        return {
            "type": "in-memory",
            "count": len(_memory_storage),
            "persistent_file": "books_data.json"
        }
    else:
        return {
            "type": "mongodb",
            "url": MONGODB_URL,
            "database": DATABASE_NAME
        }

async def clean_incomplete_books():
    """Clean and fix incomplete book data"""
    collection = get_collection()
    
    try:
        # Get all books
        cursor = collection.find({})
        books = await cursor.to_list(length=None)
        
        updated_count = 0
        deleted_count = 0
        
        for book in books:
            # Check required fields
            required_fields = ['title', 'price', 'availability', 'star_rating']
            missing_fields = [field for field in required_fields if field not in book or book[field] is None or book[field] == '']
            
            if missing_fields:
                # Add default values for missing fields
                updates = {}
                if 'title' in missing_fields:
                    # Try to extract title from URL
                    url = book.get('product_url', '')
                    if url:
                        # Extract title from URL path
                        import re
                        title_match = re.search(r'/([^/]+)_\d+/index\.html', url)
                        if title_match:
                            title = title_match.group(1).replace('-', ' ').title()
                            updates['title'] = title
                        else:
                            updates['title'] = 'Unknown Title'
                    else:
                        updates['title'] = 'Unknown Title'
                
                if 'price' in missing_fields:
                    updates['price'] = 0.0
                
                if 'availability' in missing_fields:
                    updates['availability'] = 'Unknown'
                
                if 'star_rating' in missing_fields:
                    updates['star_rating'] = 0
                
                if updates:
                    await collection.update_one({'_id': book['_id']}, {'$set': updates})
                    updated_count += 1
                    logger.info(f"✅ Updated book: {updates.get('title', book.get('title', 'unknown'))}")
        
        logger.info(f"📊 Data cleanup complete: Updated {updated_count} books")
        return updated_count
        
    except Exception as e:
        logger.error(f"❌ Failed to clean data: {e}")
        return 0