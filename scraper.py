import requests
from bs4 import BeautifulSoup
import re
import json
import csv
import time
from typing import List, Dict
from urllib.parse import urljoin, urlparse
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from database import connect_to_mongo, get_collection
from models import BookModel
import pandas as pd
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BookScraper:
    """
    🕷️ A comprehensive web scraper for books.toscrape.com
    
    Features:
    - Respectful scraping with delays
    - Pagination handling
    - Error recovery and validation
    - Multiple output formats
    - Data analysis capabilities
    """
    
    def __init__(self, base_url: str = "https://books.toscrape.com"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.books_data = []
        self.total_pages_scraped = 0
        self.errors_encountered = 0
        
    def extract_star_rating(self, star_classes: List[str]) -> int:
        """
        Convert star rating class to numeric value
        Example: ['star-rating', 'Three'] -> 3
        """
        rating_map = {
            'One': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5
        }
        
        if isinstance(star_classes, str):
            star_classes = star_classes.split()
            
        for class_name in star_classes:
            if class_name in rating_map:
                return rating_map[class_name]
        
        logger.warning(f"Could not parse star rating: {star_classes}")
        return 0
    
    def clean_price(self, price_text: str) -> float:
        """Extract numeric price from text like '£51.77'"""
        try:
            # Remove currency symbols and spaces
            price_clean = re.sub(r'[^\d.]', '', price_text)
            return float(price_clean) if price_clean else 0.0
        except (ValueError, TypeError):
            logger.warning(f"Could not parse price: {price_text}")
            return 0.0
    
    def clean_availability(self, availability_text: str) -> str:
        """Clean and standardize availability text"""
        if not availability_text:
            return "Unknown"
        
        cleaned = availability_text.strip().replace('\n', ' ')
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        if 'in stock' in cleaned.lower():
            return "In stock"
        elif 'out of stock' in cleaned.lower():
            return "Out of stock"
        else:
            return cleaned
    
    def scrape_page(self, page_url: str) -> List[Dict]:
        """
        🔍 Scrape a single page and extract book information
        """
        try:
            logger.info(f"📖 Scraping page: {page_url}")
            response = self.session.get(page_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            books_on_page = []
            
            # Find all book containers
            book_containers = soup.find_all('article', class_='product_pod')
            
            if not book_containers:
                logger.warning(f"No books found on page: {page_url}")
                return []
            
            for book in book_containers:
                try:
                    # Extract title - IMPROVED LOGIC
                    title = "Unknown Title"
                    title_element = book.find('h3')
                    if title_element:
                        title_link = title_element.find('a')
                        if title_link:
                            # Try to get title from 'title' attribute first
                            title = title_link.get('title', '').strip()
                            if not title:
                                # Fallback to link text
                                title = title_link.get_text(strip=True)
                            if not title:
                                title = "Unknown Title"
                    
                    # Extract product URL
                    product_url = ''
                    if title_element:
                        title_link = title_element.find('a')
                        if title_link:
                            relative_url = title_link.get('href', '')
                            product_url = urljoin(page_url, relative_url)
                    
                    # Skip if no URL (critical field)
                    if not product_url:
                        logger.warning(f"Skipping book with no URL: {title}")
                        continue
                    
                    # Extract price - IMPROVED LOGIC
                    price = 0.0
                    price_element = book.find('p', class_='price_color')
                    if price_element:
                        price = self.clean_price(price_element.get_text(strip=True))
                    
                    # Extract availability - IMPROVED LOGIC
                    availability = "Unknown"
                    availability_element = book.find('p', class_='instock availability')
                    if availability_element:
                        availability = self.clean_availability(availability_element.get_text(strip=True))
                    
                    # Extract star rating - IMPROVED LOGIC
                    star_rating = 0
                    star_element = book.find('p', class_=re.compile('star-rating'))
                    if star_element:
                        star_classes = star_element.get('class', [])
                        star_rating = self.extract_star_rating(star_classes)
                    
                    # Validate that we have meaningful data
                    if title == "Unknown Title" and price == 0.0:
                        logger.warning(f"Skipping book with no meaningful data: {product_url}")
                        continue
                    
                    book_data = {
                        'title': title,
                        'price': price,
                        'availability': availability,
                        'star_rating': star_rating,
                        'product_url': product_url
                    }
                    
                    books_on_page.append(book_data)
                    
                except Exception as e:
                    self.errors_encountered += 1
                    logger.error(f"❌ Error extracting book data: {e}")
                    continue
            
            logger.info(f"✅ Extracted {len(books_on_page)} books from current page")
            return books_on_page
            
        except requests.RequestException as e:
            self.errors_encountered += 1
            logger.error(f"❌ Network error fetching page {page_url}: {e}")
            return []
        except Exception as e:
            self.errors_encountered += 1
            logger.error(f"❌ Unexpected error scraping page {page_url}: {e}")
            return []
    
    def get_all_pages(self) -> List[str]:
        """
        🔗 Discover all page URLs by following pagination
        """
        pages = [self.base_url]
        current_page = 1
        max_pages = 100  # Safety limit
        
        logger.info("🔍 Discovering all available pages...")
        
        while current_page < max_pages:
            try:
                next_page = current_page + 1
                page_url = f"{self.base_url}/catalogue/page-{next_page}.html"
                
                response = self.session.head(page_url, timeout=10)
                
                if response.status_code == 404:
                    logger.info(f"📄 Reached end of pages at page {current_page}")
                    break
                elif response.status_code != 200:
                    logger.warning(f"⚠️ Unexpected status {response.status_code} for page {next_page}")
                    break
                    
                pages.append(page_url)
                current_page += 1
                logger.info(f"📄 Found page {next_page}: {page_url}")
                
                # Small delay to be respectful
                time.sleep(0.5)
                
            except requests.RequestException as e:
                logger.error(f"❌ Error checking page {next_page}: {e}")
                break
            except Exception as e:
                logger.error(f"❌ Unexpected error: {e}")
                break
        
        logger.info(f"🎯 Total pages discovered: {len(pages)}")
        return pages
    
    def scrape_all_books(self) -> List[Dict]:
        """
        🚀 Main scraping method - scrape all books from all pages
        """
        start_time = time.time()
        logger.info("🕷️ Starting comprehensive book scraping...")
        
        # Reset counters
        self.books_data = []
        self.total_pages_scraped = 0
        self.errors_encountered = 0
        
        # Get all page URLs
        all_pages = self.get_all_pages()
        
        if not all_pages:
            logger.error("❌ No pages found to scrape!")
            return []
        
        # Scrape each page
        for i, page_url in enumerate(all_pages, 1):
            logger.info(f"📖 Processing page {i}/{len(all_pages)}")
            
            books_on_page = self.scrape_page(page_url)
            self.books_data.extend(books_on_page)
            self.total_pages_scraped += 1
            
            # Progress update
            if i % 10 == 0:
                logger.info(f"📊 Progress: {i}/{len(all_pages)} pages, {len(self.books_data)} books collected")
            
            # Be respectful - add delay between requests
            time.sleep(1)
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info("="*60)
        logger.info("🎉 SCRAPING COMPLETED!")
        logger.info(f"📚 Total books scraped: {len(self.books_data)}")
        logger.info(f"📄 Pages processed: {self.total_pages_scraped}")
        logger.info(f"⚠️ Errors encountered: {self.errors_encountered}")
        logger.info(f"⏱️ Time taken: {duration:.2f} seconds")
        logger.info(f"⚡ Average books per page: {len(self.books_data)/max(self.total_pages_scraped, 1):.1f}")
        logger.info("="*60)
        
        return self.books_data
    
    def save_to_json(self, filename: str = "books_data.json"):
        """💾 Save scraped data to JSON file"""
        try:
            output_data = {
                "metadata": {
                    "scraped_at": datetime.now().isoformat(),
                    "total_books": len(self.books_data),
                    "pages_scraped": self.total_pages_scraped,
                    "source": "books.toscrape.com"
                },
                "books": self.books_data
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Data saved to {filename}")
        except Exception as e:
            logger.error(f"❌ Failed to save JSON: {e}")
    
    def save_to_csv(self, filename: str = "books_data.csv"):
        """📊 Save scraped data to CSV file"""
        try:
            if self.books_data:
                df = pd.DataFrame(self.books_data)
                df.to_csv(filename, index=False, encoding='utf-8')
                logger.info(f"📊 Data saved to {filename}")
            else:
                logger.warning("⚠️ No data to save to CSV")
        except Exception as e:
            logger.error(f"❌ Failed to save CSV: {e}")
    
    async def save_to_mongodb(self):
        """🗄️ Save scraped data to MongoDB with improved error handling"""
        try:
            await connect_to_mongo()
            collection = get_collection()
            
            if not self.books_data:
                logger.warning("⚠️ No books to save to MongoDB")
                return
            
            # Clear existing data
            delete_result = await collection.delete_many({})
            logger.info(f"🗑️ Cleared {delete_result.deleted_count} existing records")
            
            # Prepare books for insertion - clean the data
            valid_books = []
            for book in self.books_data:
                try:
                    # Clean and validate book data
                    clean_book = {
                        'title': book.get('title', 'Unknown Title'),
                        'price': float(book.get('price', 0.0)),
                        'availability': book.get('availability', 'Unknown'),
                        'star_rating': int(book.get('star_rating', 0)),
                        'product_url': book.get('product_url', '')
                    }
                    
                    # Only add books with valid URLs
                    if clean_book['product_url']:
                        valid_books.append(clean_book)
                    else:
                        logger.warning(f"Skipping book without URL: {clean_book['title']}")
                        
                except Exception as e:
                    logger.error(f"❌ Failed to clean book data: {book}, Error: {e}")
                    continue
            
            if not valid_books:
                logger.warning("⚠️ No valid books to insert into MongoDB")
                return
            
            # Insert in batches to avoid memory issues
            batch_size = 100
            total_inserted = 0
            
            for i in range(0, len(valid_books), batch_size):
                batch = valid_books[i:i + batch_size]
                try:
                    result = await collection.insert_many(batch, ordered=False)
                    total_inserted += len(result.inserted_ids)
                    logger.info(f"✅ Inserted batch {i//batch_size + 1}: {len(result.inserted_ids)} books")
                except Exception as e:
                    logger.error(f"❌ Failed to insert batch {i//batch_size + 1}: {e}")
            
            logger.info(f"💾 Successfully saved {total_inserted} books to MongoDB")
                
        except Exception as e:
            logger.error(f"❌ Failed to save to MongoDB: {e}")
            raise
    
    def analyze_data(self):
        """
        📊 Perform comprehensive data analysis on scraped books
        """
        if not self.books_data:
            logger.warning("⚠️ No data to analyze")
            return
        
        try:
            df = pd.DataFrame(self.books_data)
            
            print("\n" + "="*60)
            print("📊 COMPREHENSIVE BOOK SCRAPING ANALYSIS")
            print("="*60)
            
            # Basic statistics
            total_books = len(df)
            avg_price = df['price'].mean()
            books_in_stock = len(df[df['availability'].str.contains('In stock', case=False, na=False)])
            five_star_books = len(df[df['star_rating'] == 5])
            
            print(f"📚 Total Books Scraped: {total_books:,}")
            print(f"💰 Average Price: £{avg_price:.2f}")
            print(f"📦 Books In Stock: {books_in_stock:,} ({books_in_stock/total_books*100:.1f}%)")
            print(f"⭐ Five-Star Books: {five_star_books:,} ({five_star_books/total_books*100:.1f}%)")
            
            print(f"\n🕷️ Scraping Performance:")
            print(f"📄 Pages Processed: {self.total_pages_scraped}")
            print(f"⚠️ Errors Encountered: {self.errors_encountered}")
            print(f"📈 Success Rate: {((total_books)/(total_books + self.errors_encountered)*100):.1f}%")
            
            print("\n" + "-"*60)
            print("🏆 TOP 10 MOST EXPENSIVE BOOKS")
            print("-"*60)
            
            top_10_expensive = df.nlargest(10, 'price')
            for idx, (_, book) in enumerate(top_10_expensive.iterrows(), 1):
                title_short = book['title'][:45] + "..." if len(book['title']) > 45 else book['title']
                stars = "⭐" * book['star_rating']
                print(f"{idx:2d}. {title_short:48} £{book['price']:6.2f} {stars}")
            
            print("\n" + "-"*60)
            print("📊 DETAILED STATISTICS")
            print("-"*60)
            
            # Price statistics
            print(f"💰 Price Analysis:")
            print(f"   • Minimum Price: £{df['price'].min():.2f}")
            print(f"   • Maximum Price: £{df['price'].max():.2f}")
            print(f"   • Median Price: £{df['price'].median():.2f}")
            print(f"   • Standard Deviation: £{df['price'].std():.2f}")
            
            # Rating distribution
            print(f"\n⭐ Rating Distribution:")
            rating_counts = df['star_rating'].value_counts().sort_index()
            for rating, count in rating_counts.items():
                stars = "⭐" * rating if rating > 0 else "❌"
                percentage = count/total_books*100
                print(f"   • {stars:15} {count:4,} books ({percentage:5.1f}%)")
            
            # Availability analysis
            print(f"\n📦 Availability Analysis:")
            availability_counts = df['availability'].value_counts()
            for availability, count in availability_counts.items():
                percentage = count/total_books*100
                print(f"   • {availability:20} {count:4,} books ({percentage:5.1f}%)")
            
            print("="*60)
            
        except Exception as e:
            logger.error(f"❌ Analysis failed: {e}")


# Standalone execution
async def main():
    """
    🚀 Main function to run the scraper independently
    """
    scraper = BookScraper()
    
    try:
        # Scrape all books
        books = scraper.scrape_all_books()
        
        if books:
            # Save to different formats
            scraper.save_to_json()
            scraper.save_to_csv()
            await scraper.save_to_mongodb()
            
            # Analyze the data
            scraper.analyze_data()
        else:
            logger.error("❌ No books were scraped!")
            
    except KeyboardInterrupt:
        logger.info("⚠️ Scraping interrupted by user")
    except Exception as e:
        logger.error(f"❌ Scraping failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())