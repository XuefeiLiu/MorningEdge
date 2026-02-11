"""
Massive API collector for stock news.
API Documentation: https://massive.com/docs/rest/stocks/news
"""
import os
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from hashlib import md5
import httpx

from backend.models import NewsItem, Category, ImpactLevel
from .base import BaseCollector

logger = logging.getLogger(__name__)


class MassiveCollector(BaseCollector):
    """Collector for Massive API news."""
    
    DEFAULT_API_URL = "https://api.massive.com/v2/reference/news"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None
    ):
        """
        Initialize Massive collector.
        
        Args:
            api_key: API key for authentication
            api_url: API base URL
        """
        super().__init__("massive", source_type="news")
        
        # Get API key from parameter, environment variable, or config
        self.api_key = api_key
        if not self.api_key:
            self.api_key = os.getenv("MASSIVE_API_KEY")
        if not self.api_key:
            from dotenv import load_dotenv
            load_dotenv()
            self.api_key = os.getenv("MASSIVE_API_KEY")
        
        # Normalize API key: remove Unicode quotation marks and whitespace
        # Some users might copy-paste API keys with Unicode quotes instead of ASCII quotes
        if self.api_key:
            api_key_str = str(self.api_key).strip()
            # Replace Unicode quotation marks with ASCII quotes, then remove all quotes
            api_key_str = api_key_str.replace('"', '"').replace('"', '"').replace("'", "'").replace("'", "'")
            api_key_str = api_key_str.strip('"\'')  # Remove any remaining quotes
            self.api_key = api_key_str
        
        self.api_url = api_url or self.DEFAULT_API_URL
        
        if not self.api_key:
            self.mark_unavailable("MASSIVE_API_KEY not configured (check .env file)")
            logger.warning("Massive API key not found. Please set MASSIVE_API_KEY in .env file")
        else:
            logger.info("Massive API key loaded successfully")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from Massive API for symbols.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects
        """
        if not self.is_available:
            logger.info(f"Massive collector unavailable: {self._last_error}")
            return []
        
        news_items = []
        
        try:
            # Configure httpx client with proper encoding for Unicode support
            # httpx handles UTF-8 by default, but we ensure proper error handling
            async with httpx.AsyncClient(timeout=30.0) as client:
                for symbol in symbols:
                    symbol_news = await self._collect_for_symbol(
                        client, symbol, start_time, end_time
                    )
                    news_items.extend(symbol_news)
        
        except Exception as e:
            logger.error(f"Error in Massive collection: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return news_items
    
    async def _collect_for_symbol(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect news for a single symbol."""
        all_news = []
        
        # Ensure timezone-aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        # Format dates for API
        # Massive API uses dot notation for date filters: published_utc.gte, published_utc.lte
        # Use date format (YYYY-MM-DD) for the filters
        start_date = start_time.strftime("%Y-%m-%d")
        end_date = end_time.strftime("%Y-%m-%d")
        
        # Build query parameters
        # Use dot notation for date range filters (gte = greater than or equal, lte = less than or equal)
        # Ensure all string values are properly encoded (httpx handles UTF-8 automatically)
        params = {
            "ticker": str(symbol),  # Ensure it's a string
            "sort": "published_utc",
            "order": "desc",
            "limit": "1000"  # Request 100 items per page (default is 10, max is 1000)
        }
        
        # Add date range filters using dot notation
        # published_utc.gte = articles published on or after start_date
        # published_utc.lte = articles published on or before end_date
        params["published_utc.gte"] = str(start_date)
        params["published_utc.lte"] = str(end_date)
        
        # We'll still filter by exact time window client-side to ensure precision
        
        # Add API key to headers
        # Note: Adjust authentication method based on actual Massive API requirements
        # Common patterns: Authorization header, X-API-Key header, or apikey query param
        headers = {}
        if self.api_key:
            # API key is already normalized in __init__, but ensure it's a string
            api_key_str = str(self.api_key)
            # Try common authentication patterns
            headers["Authorization"] = f"Bearer {api_key_str}"
            # Alternative if Bearer doesn't work:
            # headers["X-API-Key"] = self.api_key
            # Or add to params: params["apikey"] = self.api_key
        
        try:
            # httpx handles UTF-8 encoding automatically for URLs and parameters
            # All params are already strings, so no additional encoding needed
            logger.debug(f"Making initial Massive API request for {symbol}...")
            response = await client.get(self.api_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # Extract results array
            results = data.get("results", [])
            logger.debug(f"Massive API response returned {len(results)} items for {symbol}")
            all_news.extend(results)
            
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self.mark_unavailable("Invalid API key")
                logger.error(f"Massive API authentication failed: {e}")
            elif e.response.status_code == 429:
                logger.warning(f"Massive API rate limit exceeded for {symbol}")
            elif e.response.status_code == 400:
                # Bad request - might be due to date format or authentication
                # Log the response body for debugging
                try:
                    error_body = e.response.json()
                    logger.error(f"Massive API 400 error for {symbol}: {error_body}")
                except:
                    logger.error(f"Massive API 400 error for {symbol}: {e.response.text}")
            else:
                logger.error(f"Massive API HTTP error for {symbol}: {e}")
        except UnicodeEncodeError as e:
            # Handle Unicode encoding errors specifically
            try:
                error_repr = repr(e)
                logger.error(f"Unicode encoding error fetching from Massive API for {symbol}: {error_repr}")
            except:
                logger.error(f"Unicode encoding error fetching from Massive API for {symbol}: [Unable to format error]")
        except Exception as e:
            # Ensure error message is properly encoded for logging
            # Use repr() to safely handle Unicode in exception messages
            try:
                error_repr = repr(e)
                logger.error(f"Error fetching from Massive API for {symbol}: {error_repr}")
            except Exception as log_error:
                # Fallback if even logging fails
                logger.error(f"Error fetching from Massive API for {symbol}: [Error occurred, unable to log details: {type(log_error).__name__}]")
        
        # Convert to NewsItem objects and filter by time window
        news_items = []
        for item in all_news:
            news_item = self._dict_to_news_item(item, symbol)
            if news_item:
                # Filter by time window (API may return items slightly outside range)
                if start_time <= news_item.published_at <= end_time:
                    news_items.append(news_item)
        
        return news_items
    
    def _dict_to_news_item(
        self,
        item: Dict[str, Any],
        symbol: str
    ) -> Optional[NewsItem]:
        """Convert API response item to NewsItem."""
        title = item.get("title", "")
        if not title:
            return None
        
        # Parse published_utc (RFC3339 format: YYYY-MM-DDTHH:MM:SSZ)
        published_utc_str = item.get("published_utc", "")
        try:
            if published_utc_str:
                # Handle RFC3339 format
                if published_utc_str.endswith("Z"):
                    published_utc_str = published_utc_str.replace("Z", "+00:00")
                published_at = datetime.fromisoformat(published_utc_str)
            else:
                published_at = datetime.now(timezone.utc)
        except (ValueError, TypeError):
            published_at = datetime.now(timezone.utc)
        
        # Ensure timezone-aware
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        
        # Extract tickers from article (may include multiple)
        article_tickers = item.get("tickers", [])
        if symbol.upper() not in [t.upper() for t in article_tickers]:
            # Add the requested symbol if not already in list
            article_tickers.append(symbol.upper())
        
        # Get publisher information
        publisher = item.get("publisher", {})
        publisher_name = publisher.get("name", "Massive") if isinstance(publisher, dict) else "Massive"
        
        # Generate unique ID
        article_id = item.get("id", "")
        article_url = item.get("article_url", "")
        if article_id:
            news_id = md5(f"{article_id}{article_url}".encode('utf-8')).hexdigest()[:12]
        else:
            news_id = md5(f"{title}{published_utc_str}".encode('utf-8')).hexdigest()[:12]
        
        return NewsItem(
            id=f"massive_{news_id}",
            ticker=symbol.upper(),
            published_at=published_at,
            title=title,
            summary=item.get("description"),
            url=article_url or item.get("amp_url"),
            source=publisher_name,
            collector="massive"
        )
