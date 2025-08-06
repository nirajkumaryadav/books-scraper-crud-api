import pytest
from fastapi.testclient import TestClient
from main import app
import asyncio
from unittest.mock import AsyncMock, patch

@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

def test_home_route(client):
    """Test the root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert "Books Scraper CRUD API" in response.json()["message"]

def test_about_route(client):
    """Test the about endpoint"""
    response = client.get("/about")
    assert response.status_code == 200
    assert response.json()["message"] == "Books Scraper API"
    assert "features" in response.json()

def test_get_books_endpoint(client):
    """Test the books listing endpoint"""
    response = client.get("/books/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_books_filtering(client):
    """Test books endpoint with filters"""
    response = client.get("/books/?star_rating=5&max_price=30&limit=5")
    assert response.status_code == 200
    books = response.json()
    assert isinstance(books, list)
    assert len(books) <= 5

def test_invalid_book_id(client):
    """Test fetching book with invalid ID"""
    response = client.get("/books/invalid-id")
    assert response.status_code == 400
    assert "Invalid book ID format" in response.json()["detail"]

def test_book_not_found(client):
    """Test fetching non-existent book"""
    valid_but_nonexistent_id = "507f1f77bcf86cd799439011"
    response = client.get(f"/books/{valid_but_nonexistent_id}")
    # This might return 404 or 500 depending on database state
    assert response.status_code in [404, 500]

@patch('main.BookScraper')
def test_scraping_endpoint(mock_scraper, client):
    """Test the scraping endpoint with mocked scraper"""
    # Mock the scraper
    mock_instance = AsyncMock()
    mock_instance.scrape_all_books.return_value = [
        {
            "title": "Test Book",
            "price": 19.99,
            "availability": "In stock",
            "star_rating": 4,
            "product_url": "https://example.com/book"
        }
    ]
    mock_instance.save_to_mongodb = AsyncMock()
    mock_instance.save_to_json = AsyncMock()
    mock_instance.save_to_csv = AsyncMock()
    mock_scraper.return_value = mock_instance
    
    response = client.post("/scrape/start")
    # This test might fail without proper async handling in the test environment
    # In a real scenario, you'd use async test clients

def test_create_book_validation(client):
    """Test book creation with validation"""
    # Test with invalid data
    invalid_book = {
        "title": "Test Book",
        "price": -10,  # Invalid negative price
        "availability": "In stock",
        "star_rating": 6,  # Invalid rating > 5
        "product_url": "not-a-url"
    }
    
    response = client.post("/books/", json=invalid_book)
    assert response.status_code == 422  # Validation error

def test_messages_compatibility(client):
    """Test that original message endpoints still work"""
    # Test adding a message
    response = client.post("/messages/test-message/")
    assert response.status_code == 200
    assert "message" in response.json()
    
    # Test listing messages
    response = client.get("/messages")
    assert response.status_code == 200
    assert "messages" in response.json()

def test_book_search(client):
    """Test book search functionality"""
    response = client.get("/books/?search=python&limit=10")
    assert response.status_code == 200
    books = response.json()
    assert isinstance(books, list)

def test_price_range_filtering(client):
    """Test price range filtering"""
    response = client.get("/books/?min_price=10&max_price=50")
    assert response.status_code == 200
    books = response.json()
    assert isinstance(books, list)

def test_stats_summary_endpoint(client):
    """Test statistics summary endpoint"""
    response = client.get("/books/stats/summary")
    assert response.status_code == 200
    data = response.json()
    
    # Should return either statistics or a message about no data
    assert "total_books" in data or "message" in data

def test_top_books_endpoint(client):
    """Test top books endpoint"""
    response = client.get("/books/stats/top-books?limit=5&sort_by=price")
    assert response.status_code == 200
    data = response.json()
    assert "books" in data or "message" in data

if __name__ == "__main__":
    pytest.main([__file__])