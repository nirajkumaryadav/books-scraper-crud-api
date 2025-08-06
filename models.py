from pydantic import BaseModel, Field, ConfigDict, field_validator, ValidationError
from typing import Optional
from bson import ObjectId
from bson.errors import InvalidId


class PyObjectId(ObjectId):
    """Custom ObjectId class for Pydantic v2 compatibility"""
    
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema
        
        def validate_object_id(value):
            if isinstance(value, ObjectId):
                return value
            if isinstance(value, str):
                try:
                    return ObjectId(value)
                except InvalidId:
                    raise ValueError("Invalid ObjectId")
            raise ValueError("Invalid ObjectId")
        
        return core_schema.no_info_plain_validator_function(
            validate_object_id,
            serialization=core_schema.to_string_ser_schema()
        )


class BookModel(BaseModel):
    """
    📚 Complete book data model - handles incomplete scraped data gracefully
    """
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str},
        str_strip_whitespace=True,
        validate_assignment=True
    )
    
    id: Optional[str] = Field(default=None, alias="_id")
    title: Optional[str] = Field(default="Unknown Title", description="Book title")
    price: Optional[float] = Field(default=0.0, description="Book price", ge=0)
    availability: Optional[str] = Field(default="Unknown", description="Stock availability status")
    star_rating: Optional[int] = Field(default=0, description="Star rating (0-5)", ge=0, le=5)
    product_url: str = Field(default="", description="Product page URL")
    
    @field_validator('price', mode='before')
    @classmethod
    def validate_price(cls, v):
        """Ensure price is always a valid float"""
        if v is None or v == '':
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0
    
    @field_validator('star_rating', mode='before')
    @classmethod
    def validate_star_rating(cls, v):
        """Ensure star_rating is always a valid int between 0-5"""
        if v is None or v == '':
            return 0
        try:
            rating = int(v)
            return max(0, min(5, rating))
        except (ValueError, TypeError):
            return 0
    
    @field_validator('title', mode='before')
    @classmethod
    def validate_title(cls, v):
        """Ensure title is never empty"""
        if not v or (isinstance(v, str) and v.strip() == ''):
            return "Unknown Title"
        return str(v).strip()
    
    @field_validator('availability', mode='before')
    @classmethod
    def validate_availability(cls, v):
        """Ensure availability is never empty"""
        if not v or (isinstance(v, str) and v.strip() == ''):
            return "Unknown"
        return str(v).strip()
    
    @field_validator('product_url', mode='before')
    @classmethod
    def validate_product_url(cls, v):
        """Ensure product_url is never None"""
        if not v:
            return ""
        return str(v).strip()
    
    @classmethod
    def from_mongo(cls, data: dict):
        """Convert MongoDB document to Pydantic model with robust validation"""
        if data is None:
            return None
        
        try:
            # Convert ObjectId to string
            if "_id" in data and data["_id"] is not None:
                data["_id"] = str(data["_id"])
            
            # Pre-clean the data before passing to Pydantic
            cleaned_data = {}
            
            # Handle ID
            cleaned_data['_id'] = data.get('_id')
            
            # Handle title with fallback
            title = data.get('title')
            if not title or (isinstance(title, str) and title.strip() == ''):
                cleaned_data['title'] = "Unknown Title"
            else:
                cleaned_data['title'] = str(title).strip()
            
            # Handle price with validation
            price = data.get('price')
            try:
                cleaned_data['price'] = float(price) if price is not None else 0.0
            except (ValueError, TypeError):
                cleaned_data['price'] = 0.0
            
            # Handle availability
            availability = data.get('availability')
            if not availability or (isinstance(availability, str) and availability.strip() == ''):
                cleaned_data['availability'] = "Unknown"
            else:
                cleaned_data['availability'] = str(availability).strip()
            
            # Handle star_rating with validation
            star_rating = data.get('star_rating')
            try:
                rating = int(star_rating) if star_rating is not None else 0
                cleaned_data['star_rating'] = max(0, min(5, rating))
            except (ValueError, TypeError):
                cleaned_data['star_rating'] = 0
            
            # Handle product_url
            product_url = data.get('product_url', '')
            cleaned_data['product_url'] = str(product_url).strip() if product_url else ""
            
            return cls(**cleaned_data)
            
        except Exception as e:
            # If all else fails, create a minimal valid object
            print(f"Warning: Failed to create BookModel from data {data}: {e}")
            return cls(
                _id=str(data.get('_id', '')),
                title="Unknown Title",
                price=0.0,
                availability="Unknown",
                star_rating=0,
                product_url=data.get('product_url', '')
            )


class BookCreate(BaseModel):
    """
    ➕ Model for creating new books - all fields required
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Advanced Web Scraping with Python",
                "price": 29.99,
                "availability": "In stock",
                "star_rating": 5,
                "product_url": "https://books.toscrape.com/book123"
            }
        }
    )
    
    title: str = Field(..., description="Book title", min_length=1, max_length=500)
    price: float = Field(..., description="Book price", ge=0, le=1000)
    availability: str = Field(..., description="Stock availability", max_length=100)
    star_rating: int = Field(..., description="Star rating (1-5)", ge=1, le=5)
    product_url: str = Field(..., description="Product page URL", max_length=1000)


class BookUpdate(BaseModel):
    """
    ✏️ Model for updating existing books (all fields optional)
    """
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "price": 24.99,
                "star_rating": 4,
                "availability": "In stock"
            }
        }
    )
    
    title: Optional[str] = Field(None, description="Book title", min_length=1, max_length=500)
    price: Optional[float] = Field(None, description="Book price", ge=0, le=1000)
    availability: Optional[str] = Field(None, description="Stock availability", max_length=100)
    star_rating: Optional[int] = Field(None, description="Star rating (0-5)", ge=0, le=5)
    product_url: Optional[str] = Field(None, description="Product page URL", max_length=1000)


class MsgPayload(BaseModel):
    """💌 Original message model for compatibility"""
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "msg_id": 1,
                "msg_name": "Hello World"
            }
        }
    )
    
    msg_id: int = Field(..., description="Message ID")
    msg_name: str = Field(..., description="Message name", min_length=1, max_length=100)


class ScrapingResponse(BaseModel):
    """📊 Response model for scraping operations"""
    message: str
    total_books: int
    status: str
    files_created: Optional[list] = None
    database: Optional[str] = None


class BookListResponse(BaseModel):
    """📚 Response model for book listings"""
    books: list[BookModel]
    total: int
    page: int
    limit: int


class StatsResponse(BaseModel):
    """📈 Response model for statistics"""
    summary: dict
    rating_distribution: dict
    availability_distribution: dict


class ErrorResponse(BaseModel):
    """❌ Error response model"""
    detail: str
    error_type: Optional[str] = None
    timestamp: Optional[str] = None


class AboutResponse(BaseModel):
    """ℹ️ Response model for API information"""
    message: str
    description: str
    features: list[str]
    endpoints: dict
    version: Optional[str] = None
    database: Optional[str] = None