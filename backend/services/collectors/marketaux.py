"""
Marketaux API collector for stock news.
API Documentation: https://www.marketaux.com/documentation
"""
import os
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from hashlib import md5
import httpx

from backend.models import NewsItem, Category, ImpactLevel
from .base import BaseCollector

logger = logging.getLogger(__name__)


class MarketauxCollector(BaseCollector):
    """Collector for Marketaux API news."""
    
    DEFAULT_API_URL = "https://api.marketaux.com/v1/news/all"
    DEFAULT_LIMIT = 100
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None
    ):
        """
        Initialize Marketaux collector.
        
        Args:
            api_key: API token for authentication
            api_url: API base URL
        """
        super().__init__("marketaux", source_type="news")
        
        # Get API key from parameter, environment variable, or config
        self.api_key = api_key
        if not self.api_key:
            self.api_key = os.getenv("MARKETAUX_API_KEY")
        if not self.api_key:
            from dotenv import load_dotenv
            load_dotenv()
            self.api_key = os.getenv("MARKETAUX_API_KEY")
        
        self.api_url = api_url or self.DEFAULT_API_URL
        
        if not self.api_key:
            self.mark_unavailable("MARKETAUX_API_KEY not configured (check .env file)")
            logger.warning("Marketaux API key not found. Please set MARKETAUX_API_KEY in .env file")
        else:
            logger.info("Marketaux API key loaded successfully")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from Marketaux API for symbols.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects
        """
        if not self.is_available:
            logger.info(f"Marketaux collector unavailable: {self._last_error}")
            return []
        
        news_items = []
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Marketaux supports multiple symbols in one request
                symbol_news = await self._collect_for_symbols(
                    client, symbols, start_time, end_time
                )
                news_items.extend(symbol_news)
        
        except Exception as e:
            logger.error(f"Error in Marketaux collection: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return news_items
    
    async def _collect_for_symbols(
        self,
        client: httpx.AsyncClient,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect news for multiple symbols in a single request."""
        all_news = []
        
        # Ensure timezone-aware
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        # Format dates for API
        # Marketaux supports: Y-m-d\TH:i:s | Y-m-d\TH:i | Y-m-d\TH | Y-m-d | Y-m | Y
        # Using Y-m-d\TH:i:s format for precision
        published_after = start_time.strftime("%Y-%m-%dT%H:%M:%S")
        published_before = end_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        # Build query parameters
        # Marketaux supports comma-separated symbols
        params = {
            "api_token": self.api_key,
            "symbols": ",".join(symbols),
            "published_after": published_after,
            "published_before": published_before,
            "limit": self.DEFAULT_LIMIT,
            "language": "en",  # Filter to English by default
            "filter_entities": "true",  # Only return entities matching the query
        }
        
        try:
            response = await client.get(self.api_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Extract results array
            results = data.get("data", [])
            all_news.extend(results)
            
            # Handle pagination if needed
            meta = data.get("meta", {})
            found = meta.get("found", 0)
            returned = meta.get("returned", 0)
            
            # If there are more results and we haven't reached the limit, paginate
            if found > returned and len(all_news) < self.DEFAULT_LIMIT:
                page = 2
                while len(all_news) < self.DEFAULT_LIMIT and page * returned <= found:
                    try:
                        pagination_params = params.copy()
                        pagination_params["page"] = page
                        pagination_response = await client.get(self.api_url, params=pagination_params)
                        pagination_response.raise_for_status()
                        pagination_data = pagination_response.json()
                        pagination_results = pagination_data.get("data", [])
                        all_news.extend(pagination_results)
                        page += 1
                    except Exception as e:
                        logger.warning(f"Error paginating Marketaux API: {e}")
                        break
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self.mark_unavailable("Invalid API token")
                logger.error(f"Marketaux API authentication failed: {e}")
            elif e.response.status_code == 402:
                logger.warning(f"Marketaux API usage limit reached")
            elif e.response.status_code == 429:
                logger.warning(f"Marketaux API rate limit exceeded")
            elif e.response.status_code == 400:
                try:
                    error_body = e.response.json()
                    logger.error(f"Marketaux API 400 error: {error_body}")
                except:
                    logger.error(f"Marketaux API 400 error: {e.response.text}")
            else:
                logger.error(f"Marketaux API HTTP error: {e}")
        except Exception as e:
            logger.error(f"Error fetching from Marketaux API: {e}")
        
        # Convert to NewsItem objects and filter by time window
        news_items = []
        for item in all_news:
            news_item = self._dict_to_news_item(item, symbols)
            if news_item:
                # Filter by time window (API may return items slightly outside range)
                if start_time <= news_item.published_at <= end_time:
                    news_items.append(news_item)
        
        return news_items
    
    def _dict_to_news_item(
        self,
        item: Dict[str, Any],
        symbols: List[str]
    ) -> Optional[NewsItem]:
        """Convert API response item to NewsItem."""
        title = item.get("title", "")
        if not title:
            return None
        
        # Parse published_at (format: "2024-11-08T01:24:00.000000Z")
        published_at_str = item.get("published_at", "")
        try:
            if published_at_str:
                # Handle RFC3339 format with microseconds
                if published_at_str.endswith("Z"):
                    published_at_str = published_at_str.replace("Z", "+00:00")
                published_at = datetime.fromisoformat(published_at_str.replace(".000000", ""))
            else:
                published_at = datetime.now(timezone.utc)
        except (ValueError, TypeError):
            published_at = datetime.now(timezone.utc)
        
        # Ensure timezone-aware
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        
        # Extract entities from article
        entities = item.get("entities", [])
        article_symbols = []
        if entities:
            for entity in entities:
                symbol = entity.get("symbol")
                if symbol:
                    article_symbols.append(symbol.upper())
        
        # If no entities found, use the requested symbols
        if not article_symbols:
            article_symbols = [s.upper() for s in symbols]
        
        # Get source information
        source_domain = item.get("source", "marketaux.com")
        
        # Generate unique ID from UUID or title
        article_uuid = item.get("uuid", "")
        article_url = item.get("url", "")
        if article_uuid:
            news_id = md5(article_uuid.encode()).hexdigest()[:12]
        else:
            news_id = md5(f"{title}{published_at_str}".encode()).hexdigest()[:12]
        
        # Determine impact level based on sentiment if available
        impact_level = ImpactLevel.LOW
        if entities:
            # Check if any entity has strong sentiment
            for entity in entities:
                sentiment = entity.get("sentiment_score", 0)
                if abs(sentiment) > 0.5:
                    impact_level = ImpactLevel.HIGH
                    break
                elif abs(sentiment) > 0.2:
                    impact_level = ImpactLevel.MEDIUM
        
        # Use first symbol from article_symbols, or first from requested symbols
        ticker = article_symbols[0] if article_symbols else (symbols[0] if symbols else "UNKNOWN")
        
        return NewsItem(
            id=f"marketaux_{news_id}",
            ticker=ticker,
            published_at=published_at,
            title=title,
            summary=item.get("description") or item.get("snippet"),
            url=article_url,
            source=source_domain,
            collector="marketaux"
        )
