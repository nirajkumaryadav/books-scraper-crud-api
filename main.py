from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from typing import Optional, List
import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from bson.errors import InvalidId
from pydantic import ValidationError

from models import (
    BookModel, 
    BookCreate, 
    BookUpdate, 
    MsgPayload, 
    AboutResponse,
    ScrapingResponse
)
from database import connect_to_mongo, close_mongo_connection, get_collection, clean_incomplete_books
from scraper import BookScraper

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Books Scraper CRUD API",
    description="A comprehensive API for scraping and managing book data from books.toscrape.com",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Event handlers for database connection
@app.on_event("startup")
async def startup_event():
    """🚀 Initialize database connection on startup"""
    await connect_to_mongo()
    logger.info("🎯 Books Scraper API is ready!")

@app.on_event("shutdown")
async def shutdown_event():
    """💤 Clean shutdown of database connections"""
    await close_mongo_connection()
    logger.info("👋 Books Scraper API shutdown complete")

# Original routes (keeping existing functionality)
messages_list: dict[int, MsgPayload] = {}

@app.get("/")
def root() -> dict[str, str]:
    """🏠 API root endpoint"""
    return {
        "message": "Books Scraper CRUD API - Ready to serve! 📚",
        "docs": "/docs",
        "version": "1.0.0",
        "status": "active"
    }

@app.get("/about", response_model=AboutResponse)
def about():
    """ℹ️ Get API information and available endpoints"""
    return AboutResponse(
        message="Books Scraper API",
        description="Scrape and manage book data from books.toscrape.com",
        features=["Web Scraping", "CRUD Operations", "MongoDB Integration", "Data Analysis"],
        endpoints={
            "scraping": ["/scrape/start", "/scrape/analysis"],
            "books": ["/books/", "/books/{id}"],
            "stats": ["/books/stats/summary", "/books/stats/top-books"],
            "admin": ["/admin/cleanup-data", "/admin/clear-all"]
        },
        version="1.0.0",
        database="MongoDB with fallback to in-memory storage"
    )

# SCRAPER ENDPOINTS

@app.post("/scrape/start", response_model=ScrapingResponse)
async def start_scraping():
    """
    🚀 Start the web scraping process for books.toscrape.com
    """
    try:
        logger.info("🎯 Starting book scraping process...")
        scraper = BookScraper()
        
        # Run scraping in background
        books = scraper.scrape_all_books()
        
        if not books:
            return ScrapingResponse(
                message="No books found during scraping",
                total_books=0,
                status="warning",
                files_created=[],
                database="No data to save"
            )
        
        # Save to MongoDB
        await scraper.save_to_mongodb()
        
        # Save to files
        scraper.save_to_json()
        scraper.save_to_csv()
        
        logger.info(f"✅ Scraping completed! Found {len(books)} books")
        
        return ScrapingResponse(
            message="✅ Scraping completed successfully!",
            total_books=len(books),
            status="success",
            files_created=["books_data.json", "books_data.csv"],
            database="MongoDB updated"
        )
    except Exception as e:
        logger.error(f"❌ Scraping failed: {e}")
        raise HTTPException(status_code=500, detail=f"❌ Scraping failed: {str(e)}")

@app.get("/scrape/analysis")
async def get_scraping_analysis():
    """
    📊 Get comprehensive analysis of scraped book data
    """
    try:
        collection = get_collection()
        
        # Get total count
        total_books = await collection.count_documents({})
        
        if total_books == 0:
            return {
                "message": "No books in database. Run /scrape/start first.",
                "total_books": 0,
                "suggestion": "Visit /scrape/start to populate the database"
            }
        
        # Get average price
        pipeline = [{"$group": {"_id": None, "avg_price": {"$avg": "$price"}}}]
        avg_result = await collection.aggregate(pipeline).to_list(1)
        avg_price = avg_result[0]["avg_price"] if avg_result else 0
        
        # Count books in stock
        in_stock_count = await collection.count_documents({
            "availability": {"$regex": "In stock", "$options": "i"}
        })
        
        # Count 5-star books
        five_star_count = await collection.count_documents({"star_rating": 5})
        
        # Get top 10 most expensive books
        top_expensive = await collection.find().sort("price", -1).limit(10).to_list(10)
        
        # Get rating distribution
        rating_pipeline = [
            {"$group": {"_id": "$star_rating", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        rating_dist = await collection.aggregate(rating_pipeline).to_list(6)
        
        return {
            "summary": {
                "total_books": total_books,
                "average_price": round(avg_price, 2),
                "books_in_stock": in_stock_count,
                "five_star_books": five_star_count,
                "stock_percentage": round((in_stock_count / total_books) * 100, 1)
            },
            "top_10_expensive": [
                {
                    "title": book.get("title", "Unknown Title")[:50] + "..." if len(book.get("title", "")) > 50 else book.get("title", "Unknown Title"),
                    "price": book.get("price", 0),
                    "star_rating": book.get("star_rating", 0),
                    "availability": book.get("availability", "Unknown")
                }
                for book in top_expensive
            ],
            "rating_distribution": {
                f"{item['_id']}_star": item["count"] for item in rating_dist
            }
        }
    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"❌ Analysis failed: {str(e)}")

# BOOK CRUD ENDPOINTS

@app.post("/books/", response_model=BookModel)
async def create_book(book: BookCreate):
    """➕ Create a new book entry with better validation"""
    try:
        collection = get_collection()
        
        # Convert to dict and validate
        book_dict = book.model_dump()
        
        # Insert into database
        result = await collection.insert_one(book_dict)
        
        # Retrieve the created book
        created_book = await collection.find_one({"_id": result.inserted_id})
        
        if not created_book:
            raise HTTPException(status_code=500, detail="Failed to retrieve created book")
        
        # Use from_mongo to ensure proper conversion
        return BookModel.from_mongo(created_book)
    
    except ValidationError as e:
        logger.error(f"❌ Validation error creating book: {e}")
        raise HTTPException(
            status_code=422, 
            detail=f"Validation error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"❌ Failed to create book: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create book: {str(e)}")

@app.get("/books/", response_model=List[BookModel])
async def get_books(
    skip: int = Query(0, ge=0, description="Number of books to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of books to return"),
    star_rating: Optional[int] = Query(None, ge=0, le=5, description="Filter by star rating"),
    availability: Optional[str] = Query(None, description="Filter by availability"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum price filter"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum price filter"),
    search: Optional[str] = Query(None, description="Search in book titles")
):
    """📖 Get books with advanced filtering"""
    try:
        collection = get_collection()
        
        # Build filter query
        filter_query = {}
        
        if star_rating is not None:
            filter_query["star_rating"] = star_rating
        
        if availability:
            filter_query["availability"] = {"$regex": availability, "$options": "i"}
        
        if min_price is not None or max_price is not None:
            price_filter = {}
            if min_price is not None:
                price_filter["$gte"] = min_price
            if max_price is not None:
                price_filter["$lte"] = max_price
            filter_query["price"] = price_filter
        
        if search:
            filter_query["title"] = {"$regex": search, "$options": "i"}
        
        # Execute query
        cursor = collection.find(filter_query).sort("price", -1).skip(skip).limit(limit)
        books = await cursor.to_list(length=limit)
        
        # Convert all books using the helper method
        return [BookModel.from_mongo(book) for book in books if book]
    
    except Exception as e:
        logger.error(f"❌ Failed to fetch books: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch books: {str(e)}")

@app.get("/books/{book_id}", response_model=BookModel)
async def get_book(book_id: str):
    """🔍 Get a specific book by ID"""
    try:
        collection = get_collection()
        
        if ObjectId.is_valid(book_id):
            query = {"_id": ObjectId(book_id)}
        else:
            query = {"_id": book_id}
        
        book = await collection.find_one(query)
        
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        return BookModel.from_mongo(book)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to fetch book: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch book: {str(e)}")

@app.put("/books/{book_id}", response_model=BookModel)
async def update_book(book_id: str, book_update: BookUpdate):
    """✏️ Update an existing book"""
    try:
        collection = get_collection()
        
        # Handle both ObjectId and string IDs
        if ObjectId.is_valid(book_id):
            query = {"_id": ObjectId(book_id)}
        else:
            query = {"_id": book_id}
        
        # Create update dict with only provided fields
        update_dict = {k: v for k, v in book_update.model_dump().items() if v is not None}
        
        if not update_dict:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        result = await collection.update_one(query, {"$set": update_dict})
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Book not found")
        
        # Return updated book using from_mongo method
        updated_book = await collection.find_one(query)
        return BookModel.from_mongo(updated_book)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to update book: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update book: {str(e)}")

@app.delete("/books/{book_id}")
async def delete_book(book_id: str):
    """🗑️ Delete a book"""
    try:
        collection = get_collection()
        
        # Handle both ObjectId and string IDs
        if ObjectId.is_valid(book_id):
            query = {"_id": ObjectId(book_id)}
        else:
            query = {"_id": book_id}
        
        # Get book info before deletion
        book = await collection.find_one(query)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        result = await collection.delete_one(query)
        
        return {
            "message": f"✅ Book '{book.get('title', 'Unknown')}' deleted successfully",
            "deleted_book_id": book_id,
            "status": "success"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete book: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete book: {str(e)}")

# STATISTICS ENDPOINTS

@app.get("/books/stats/summary")
async def get_books_summary():
    """📊 Get comprehensive summary statistics of all books"""
    try:
        collection = get_collection()
        
        total_books = await collection.count_documents({})
        
        if total_books == 0:
            return {
                "message": "No books in database. Run /scrape/start to populate data.",
                "total_books": 0,
                "suggestion": "Visit /scrape/start to begin scraping"
            }
        
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "total_books": {"$sum": 1},
                    "avg_price": {"$avg": "$price"},
                    "min_price": {"$min": "$price"},
                    "max_price": {"$max": "$price"},
                    "avg_rating": {"$avg": "$star_rating"}
                }
            }
        ]
        
        result = await collection.aggregate(pipeline).to_list(1)
        stats = result[0] if result else {}
        
        # Get rating distribution
        rating_pipeline = [
            {"$group": {"_id": "$star_rating", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        rating_dist = await collection.aggregate(rating_pipeline).to_list(6)
        
        # Get availability stats
        availability_pipeline = [
            {"$group": {"_id": "$availability", "count": {"$sum": 1}}}
        ]
        availability_dist = await collection.aggregate(availability_pipeline).to_list(10)
        
        return {
            "overview": {
                "total_books": stats.get("total_books", 0),
                "average_price": round(stats.get("avg_price", 0), 2),
                "average_rating": round(stats.get("avg_rating", 0), 2)
            },
            "price_analysis": {
                "minimum": stats.get("min_price", 0),
                "maximum": stats.get("max_price", 0),
                "range": round(stats.get("max_price", 0) - stats.get("min_price", 0), 2)
            },
            "rating_distribution": {
                f"{item['_id']}_star": item["count"] for item in rating_dist
            },
            "availability_distribution": {
                item["_id"]: item["count"] for item in availability_dist
            }
        }
    
    except Exception as e:
        logger.error(f"❌ Failed to get summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get summary: {str(e)}")

@app.get("/books/stats/top-books")
async def get_top_books(
    limit: int = Query(10, ge=1, le=50, description="Number of top books to return"),
    sort_by: str = Query("price", description="Sort by: price, star_rating")
):
    """🏆 Get top books sorted by price or rating"""
    try:
        collection = get_collection()
        
        sort_field = "price" if sort_by == "price" else "star_rating"
        
        top_books = await collection.find().sort(sort_field, -1).limit(limit).to_list(limit)
        
        return {
            "criteria": f"Top {limit} books by {sort_field}",
            "total_found": len(top_books),
            "books": [
                {
                    "title": book.get("title", "Unknown Title"),
                    "price": book.get("price", 0),
                    "star_rating": book.get("star_rating", 0),
                    "availability": book.get("availability", "Unknown")
                }
                for book in top_books
            ]
        }
    
    except Exception as e:
        logger.error(f"❌ Failed to get top books: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get top books: {str(e)}")

# ADMIN ENDPOINTS

@app.post("/admin/cleanup-data")
async def cleanup_data():
    """🧹 Clean up incomplete book data and fix inconsistencies"""
    try:
        logger.info("🧹 Starting data cleanup process...")
        updated_count = await clean_incomplete_books()
        
        return {
            "message": "✅ Data cleanup completed successfully",
            "updated_books": updated_count,
            "status": "success",
            "details": "Missing fields have been filled with default values"
        }
    except Exception as e:
        logger.error(f"❌ Data cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=f"Data cleanup failed: {str(e)}")

@app.delete("/admin/clear-all")
async def clear_all_data():
    """🗑️ DANGER: Clear ALL data - database and files"""
    try:
        import os
        
        # Clear database
        collection = get_collection()
        db_result = await collection.delete_many({})
        
        # Clear files
        files_deleted = []
        
        for filename in ['books_data.json', 'books_data.csv']:
            if os.path.exists(filename):
                os.remove(filename)
                files_deleted.append(filename)
        
        return {
            "message": "🧹 ALL DATA CLEARED SUCCESSFULLY!",
            "database_records_deleted": db_result.deleted_count,
            "files_deleted": files_deleted,
            "status": "success",
            "warning": "All data has been permanently deleted"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@app.get("/admin/health")
async def health_check():
    """🔍 Health check endpoint for monitoring"""
    try:
        from database import get_storage_info
        storage_info = get_storage_info()
        
        collection = get_collection()
        total_books = await collection.count_documents({})
        
        return {
            "status": "healthy",
            "api_version": "1.0.0",
            "database": storage_info,
            "total_books": total_books,
            "timestamp": "2025-08-06"
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": "2025-08-06"
        }

# Original message routes (preserved for compatibility)
@app.post("/messages/{msg_name}/")
def add_msg(msg_name: str) -> dict[str, MsgPayload]:
    """📝 Add a new message (legacy endpoint)"""
    msg_id = max(messages_list.keys()) + 1 if messages_list else 0
    messages_list[msg_id] = MsgPayload(msg_id=msg_id, msg_name=msg_name)
    return {"message": messages_list[msg_id]}

@app.get("/messages")
def message_items() -> dict[str, dict[int, MsgPayload]]:
    """📋 Get all messages (legacy endpoint)"""
    return {"messages": messages_list}

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors with helpful message"""
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Endpoint not found",
            "suggestion": "Visit /docs for available endpoints",
            "available_endpoints": ["/", "/about", "/docs", "/books/", "/scrape/start"]
        }
    )

@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle 500 errors with helpful message"""
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "suggestion": "Check logs for more details",
            "support": "This API is in development mode"
        }
    )

@app.exception_handler(422)
async def validation_exception_handler(request, exc):
    """Handle validation errors with helpful message"""
    logger.error(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation failed",
            "errors": str(exc),
            "suggestion": "Check your input data format and try again"
        }
    )

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Books Scraper CRUD API...")
    print("📖 API Documentation: http://localhost:5000/docs")
    print("🌐 Application: http://localhost:5000")
    uvicorn.run(app, host="0.0.0.0", port=5000)