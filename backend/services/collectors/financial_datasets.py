"""
Financial Datasets API collector for company news per ticker.
Similar to ai_hedge_fund's get_company_news implementation.
"""
import os
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from hashlib import md5
import asyncio
import httpx
import re

from backend.models import NewsItem, Category, ImpactLevel
from .base import BaseCollector

logger = logging.getLogger(__name__)


class FinancialDatasetsCollector(BaseCollector):
    """Collector for Financial Datasets API news."""
    
    DEFAULT_API_URL = "https://api.financialdatasets.ai/news/"
    DEFAULT_LIMIT = 100
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        cache_enabled: bool = True,
        rate_limit_backoff: Optional[List[int]] = None
    ):
        """
        Initialize Financial Datasets collector.
        
        Args:
            api_key: API key for authentication
            api_url: API base URL
            cache_enabled: Whether to use caching (in-memory for now)
            rate_limit_backoff: Backoff intervals in seconds for rate limiting
        """
        super().__init__("financial_datasets", source_type="news")
        # Get API key from parameter, environment variable, or config
        # Try multiple ways to get the API key
        self.api_key = api_key
        if not self.api_key:
            # Try environment variable directly
            self.api_key = os.getenv("FINANCIAL_DATASETS_API_KEY")
        if not self.api_key:
            # Try loading from dotenv again (in case it wasn't loaded)
            from dotenv import load_dotenv
            load_dotenv()
            self.api_key = os.getenv("FINANCIAL_DATASETS_API_KEY")
        
        self.api_url = api_url or self.DEFAULT_API_URL
        self.cache_enabled = cache_enabled
        self.rate_limit_backoff = rate_limit_backoff or [60, 90, 120, 150]
        
        # Simple in-memory cache (could be enhanced with Redis, etc.)
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        
        if not self.api_key:
            self.mark_unavailable("FINANCIAL_DATASETS_API_KEY not configured (check .env file)")
            logger.warning("Financial Datasets API key not found. Please set FINANCIAL_DATASETS_API_KEY in .env file")
        else:
            logger.info("Financial Datasets API key loaded successfully")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from Financial Datasets API for symbols.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects
        """
        if not self.is_available:
            logger.info(f"Financial Datasets unavailable: {self._last_error}")
            return []
        
        news_items = []
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                for symbol in symbols:
                    symbol_news = await self._collect_for_symbol(
                        client, symbol, start_time, end_time
                    )
                    news_items.extend(symbol_news)
        
        except Exception as e:
            logger.error(f"Error in Financial Datasets collection: {e}")
        
        return news_items
    
    async def _collect_for_symbol(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect news for a single symbol with pagination."""
        # Normalize to UTC for consistent comparisons
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        else:
            start_time = start_time.astimezone(timezone.utc)
        
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        else:
            end_time = end_time.astimezone(timezone.utc)
        
        # Check cache
        cache_key = self._get_cache_key(symbol, start_time, end_time)
        if self.cache_enabled and cache_key in self._cache:
            cached_data = self._cache[cache_key]
            return [self._dict_to_news_item(item, symbol) for item in cached_data]
        
        all_news = []
        current_end_date = end_time.strftime("%Y-%m-%d")
        start_date_str = start_time.strftime("%Y-%m-%d")
        
        while True:
            try:
                # Fetch page
                page_news = await self._fetch_page(
                    client, symbol, current_end_date, start_date_str
                )
                
                if not page_news:
                    break
                
                all_news.extend(page_news)
                
                # Check if we need to paginate
                if len(page_news) < self.DEFAULT_LIMIT:
                    break
                
                # Update end_date to oldest date from current batch
                oldest_date = min(news.get("date", "") for news in page_news if news.get("date"))
                if not oldest_date:
                    break
                
                oldest_date_str = oldest_date.split("T")[0] if "T" in oldest_date else oldest_date
                
                # Stop if we've reached or passed start_date
                if oldest_date_str <= start_date_str:
                    break
                
                current_end_date = oldest_date_str
                
            except Exception as e:
                logger.error(f"Error paginating for {symbol}: {e}")
                break
        
        # Cache results
        if self.cache_enabled and all_news:
            self._cache[cache_key] = all_news
        
        # Convert to NewsItem and filter by time window
        news_items = []
        for item in all_news:
            news_item = self._dict_to_news_item(item, symbol)
            if news_item:
                # Filter by time window
                if start_time <= news_item.published_at <= end_time:
                    news_items.append(news_item)
        
        return news_items
    
    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        ticker: str,
        end_date: str,
        start_date: Optional[str] = None,
        limit: int = None
    ) -> List[Dict[str, Any]]:
        """Fetch a single page of news."""
        limit = limit or self.DEFAULT_LIMIT
        url = f"{self.api_url}?ticker={ticker}&end_date={end_date}&limit={limit}"
        if start_date:
            url += f"&start_date={start_date}"
        
        headers = {}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        
        max_retries = len(self.rate_limit_backoff)
        for attempt in range(max_retries + 1):
            try:
                response = await client.get(url, headers=headers)
                
                # Handle rate limiting
                if response.status_code == 429 and attempt < max_retries:
                    wait_time = self.rate_limit_backoff[min(attempt, len(self.rate_limit_backoff) - 1)]
                    logger.warning(f"Rate limited (429). Waiting {wait_time}s before retry {attempt + 1}/{max_retries}...")
                    await asyncio.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                # Parse response
                news_list = data.get("news", [])
                return news_list
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < max_retries:
                    continue
                raise
            except Exception as e:
                logger.error(f"Error fetching Financial Datasets page: {e}")
                raise
        
        return []
    
    def _get_cache_key(
        self,
        ticker: str,
        start_time: datetime,
        end_time: datetime
    ) -> str:
        """Generate cache key."""
        start_str = start_time.strftime("%Y-%m-%d")
        end_str = end_time.strftime("%Y-%m-%d")
        return f"{ticker}_{start_str}_{end_str}_{self.DEFAULT_LIMIT}"
    
    def _dict_to_news_item(
        self,
        item: Dict[str, Any],
        symbol: str
    ) -> Optional[NewsItem]:
        """Convert API response item to NewsItem."""
        title = item.get("title", "")
        if not title:
            return None
        
        # Parse date
        date_str = item.get("date", "")
        try:
            if "T" in date_str:
                published_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                # For date-only strings, assume UTC and set to noon
                published_at = datetime.fromisoformat(date_str)
                published_at = published_at.replace(hour=12, minute=0, second=0, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            published_at = datetime.now(timezone.utc)
        
        # Ensure timezone-aware (UTC)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        
        # Generate unique ID
        url = item.get("url", "")
        news_id = md5(f"{url}{title}{date_str}".encode()).hexdigest()[:12]
        
        
        return NewsItem(
            id=f"fd_{news_id}",
            ticker=symbol,
            published_at=published_at,
            title=title,
            summary=None,  # API doesn't provide summary
            url=url,
            source=item.get("source", "Financial Datasets"),
            collector="financial_datasets"
        )
    
    def _detect_language(self, text: str) -> Optional[str]:
        """Detect language from text (simple check for Chinese characters)."""
        if not text:
            return "en"  # Default to English
        
        # Check for Chinese characters
        if re.search(r'[\u4e00-\u9fff]', text):
            return "zh"
        
        return "en"
