"""
NewsNow API collector for querying news per ticker across multiple platforms.
Similar to TrendRadar's platform-based queries.
"""
import json
import random
import time
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from hashlib import md5
import asyncio
import httpx

from backend.models import NewsItem, MacroEvent, Category, ImpactLevel
from backend.services.filters import FinancialNewsFilter
from .base import BaseCollector

logger = logging.getLogger(__name__)


class NewsNowCollector(BaseCollector):
    """Collector for NewsNow API - queries multiple platforms per ticker."""
    
    DEFAULT_API_URL = "https://newsnow.busiyi.world/api/s"
    
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }
    
    # Platform IDs supported (same as TrendRadar)
    SUPPORTED_PLATFORMS = {
        "toutiao": "今日头条",
        "baidu": "百度热搜",
        "wallstreetcn-hot": "华尔街见闻",
        "thepaper": "澎湃新闻",
        "bilibili-hot-search": "bilibili 热搜",
        "cls-hot": "财联社热门",
        "ifeng": "凤凰网",
        "tieba": "贴吧",
        "weibo": "微博",
        "douyin": "抖音",
        "zhihu": "知乎",
    }
    
    # Priority financial platforms (query these first, limit to these for speed)
    PRIORITY_PLATFORMS = ["wallstreetcn-hot", "cls-hot", "toutiao", "baidu"]
    
    def __init__(
        self,
        api_url: Optional[str] = None,
        platforms: Optional[Dict[str, Dict[str, Any]]] = None,
        request_interval_ms: int = 500,  # Reduced from 2000ms to 500ms for faster collection
        max_retries: int = 1,  # Reduced from 2 to 1 for faster failure
        proxy_url: Optional[str] = None
    ):
        """
        Initialize NewsNow collector.
        
        Args:
            api_url: NewsNow API base URL
            platforms: Platform configuration dict {platform_id: {enabled: bool, name: str}}
            request_interval_ms: Request interval in milliseconds (default: 500ms)
            max_retries: Maximum retry attempts (default: 1)
            proxy_url: Optional proxy URL
        """
        super().__init__("newsnow", source_type="news")
        self.api_url = api_url or self.DEFAULT_API_URL
        self.platforms = platforms or {}
        self.request_interval_ms = request_interval_ms
        self.max_retries = max_retries
        self.proxy_url = proxy_url
        
        # Initialize financial news filter (uses AI if available, keyword fallback otherwise)
        self.financial_filter = FinancialNewsFilter(use_ai=True)
        
        # Default to priority financial platforms only for faster collection
        if not self.platforms:
            for platform_id in self.PRIORITY_PLATFORMS:
                if platform_id in self.SUPPORTED_PLATFORMS:
                    self.platforms[platform_id] = {
                        "enabled": True,
                        "name": self.SUPPORTED_PLATFORMS[platform_id]
                    }
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from NewsNow API.
        
        Collects general financial news from all enabled platforms (no ticker filtering).
        News items are converted to MacroEvent for display in macro section.
        
        Args:
            symbols: List of stock ticker symbols (not used for filtering)
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects (will be converted to MacroEvent in briefing service)
        """
        news_items = []
        
        # Get enabled platforms
        enabled_platforms = [
            platform_id for platform_id, config in self.platforms.items()
            if config.get("enabled", True)
        ]
        
        if not enabled_platforms:
            logger.warning("No enabled platforms for NewsNow collector")
            return news_items
        
        try:
            # httpx uses 'proxy' (singular), not 'proxies'
            client_kwargs = {"timeout": 10.0}
            if self.proxy_url:
                client_kwargs["proxy"] = self.proxy_url
            
            async with httpx.AsyncClient(**client_kwargs) as client:
                # Collect general financial news from all platforms (no ticker filtering)
                # Query each platform once for general financial news
                for platform_id in enabled_platforms:
                    platform_news = await self._collect_from_platform(
                        client, platform_id, start_time, end_time
                    )
                    news_items.extend(platform_news)
                    logger.info(f"NewsNow: Collected {len(platform_news)} items from {platform_id}")
                    
                    # Rate limiting between platforms
                    if platform_id != enabled_platforms[-1]:
                        await asyncio.sleep(self.request_interval_ms / 1000)
        
        except Exception as e:
            logger.error(f"Error in NewsNow collection: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        logger.info(f"NewsNow: Total collected {len(news_items)} general financial news items")
        return news_items
    
    async def _collect_from_platform(
        self,
        client: httpx.AsyncClient,
        platform_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect general financial news from a single platform (no ticker filtering)."""
        news_items = []
        
        try:
            logger.info(f"NewsNow: Starting collection from platform {platform_id}")
            result = await self._fetch_platform(
                client, platform_id, None, start_time, end_time  # None = no ticker filter
            )
            if isinstance(result, Exception):
                logger.error(f"Error fetching platform {platform_id}: {result}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
            else:
                news_items.extend(result)
                logger.info(f"NewsNow: Got {len(result)} items from platform {platform_id}")
        except Exception as e:
            logger.error(f"Error collecting from platform {platform_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        return news_items
    
    async def _fetch_platform(
        self,
        client: httpx.AsyncClient,
        platform_id: str,
        symbol: Optional[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Fetch news from a single platform. If symbol is None, collect all financial news."""
        news_items = []
        url = f"{self.api_url}?id={platform_id}&latest"
        
        retries = 0
        while retries <= self.max_retries:
            try:
                response = await client.get(url, headers=self.DEFAULT_HEADERS)
                response.raise_for_status()
                
                data = response.json()
                status = data.get("status", "unknown")
                
                logger.info(f"NewsNow {platform_id}: API response status={status}, items_count={len(data.get('items', []))}")
                
                if status not in ["success", "cache"]:
                    logger.warning(f"NewsNow {platform_id}: Response status abnormal: {status}, full response: {data}")
                    raise ValueError(f"Response status abnormal: {status}")
                
                # Parse items
                items = data.get("items", [])
                platform_name = self.platforms.get(platform_id, {}).get("name", platform_id)
                
                if not items:
                    logger.warning(f"NewsNow {platform_id}: No items returned from API")
                
                items_processed = 0
                items_skipped = 0
                items_filtered = 0
                
                # First, collect and normalize all titles
                valid_items = []
                titles = []
                for index, item in enumerate(items, 1):
                    title = item.get("title", "")
                    
                    # Only skip completely invalid titles (empty or None)
                    if not title or (isinstance(title, float) and str(title).strip() == ""):
                        items_skipped += 1
                        continue
                    
                    # Normalize title
                    if isinstance(title, float):
                        title = str(int(title)) if title.is_integer() else str(title)
                    title = str(title).strip()
                    
                    # If title is still empty after normalization, skip
                    if not title:
                        items_skipped += 1
                        continue
                    
                    valid_items.append((index, item))
                    titles.append(title)
                
                # Filter titles using AI or keyword matching
                if titles:
                    is_financial_list = await self.financial_filter.filter_financial_news(titles)
                    
                    # Process items based on filter results
                    for (index, item), title, is_financial in zip(valid_items, titles, is_financial_list):
                        if not is_financial:
                            items_filtered += 1
                            continue
                        
                        items_processed += 1
                        
                        # Convert to NewsItem - only financial/economic items
                        news_item = self._item_to_news_item(
                            item, None, platform_id, platform_name, index  # None = no specific symbol
                        )
                        if news_item:
                            news_items.append(news_item)
                        else:
                            items_skipped += 1
                            logger.warning(f"NewsNow {platform_id}: Failed to convert item {index} to NewsItem: {item}")
                
                logger.info(f"NewsNow {platform_id}: {len(items)} total items, {items_processed} processed, {items_filtered} filtered (non-financial), {items_skipped} skipped, {len(news_items)} included")
                
                # Rate limiting between platforms
                if platform_id != list(self.platforms.keys())[-1]:
                    interval = self.request_interval_ms / 1000
                    jitter = random.uniform(-0.2, 0.2) * interval
                    await asyncio.sleep(max(0.05, interval + jitter))
                
                break  # Success, exit retry loop
                
            except Exception as e:
                retries += 1
                if retries <= self.max_retries:
                    base_wait = random.uniform(3, 5)
                    additional_wait = (retries - 1) * random.uniform(1, 2)
                    wait_time = base_wait + additional_wait
                    logger.warning(f"Request {platform_id} failed: {e}. Retrying in {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Request {platform_id} failed after {self.max_retries} retries: {e}")
        
        return news_items
    
    def _ticker_in_title(self, title: str, ticker: str) -> bool:
        """
        Check if ticker appears in title (case-insensitive).
        Handles variations like "AAPL" vs "Apple".
        """
        title_lower = title.lower()
        ticker_lower = ticker.lower()
        
        # Direct match
        if ticker_lower in title_lower:
            return True
        
        # Could add more sophisticated matching here
        # (e.g., company name lookup)
        
        return False
    
    def _item_to_news_item(
        self,
        item: Dict[str, Any],
        symbol: Optional[str],
        platform_id: str,
        platform_name: str,
        rank: int
    ) -> Optional[NewsItem]:
        """Convert NewsNow API item to NewsItem (for macro section). Only financial/economic items."""
        title = item.get("title", "")
        
        # Normalize title - handle various types
        if isinstance(title, float):
            title = str(int(title)) if title.is_integer() else str(title)
        elif title is None:
            title = f"News Item {rank}"  # Use fallback title if missing
        else:
            title = str(title).strip()
        
        # If title is still empty, use a default
        if not title:
            title = f"News Item {rank} from {platform_name}"
        
        url = item.get("url", "")
        mobile_url = item.get("mobileUrl", "")
        
        # Use mobile URL if available, otherwise regular URL, or empty string
        final_url = mobile_url or url or ""
        
        # Generate unique ID - use title and rank if URL is missing
        id_string = f"{final_url}{title}{platform_id}{rank}" if final_url else f"{title}{platform_id}{rank}"
        news_id = md5(id_string.encode()).hexdigest()[:12]
        
        # NewsNow doesn't provide timestamps, use current time
        published_at = datetime.utcnow()
        
        # Only financial/economic macro news items (already filtered)
        # NewsNow doesn't have specific tickers, use "MACRO" as placeholder
        return NewsItem(
            id=f"newsnow_{platform_id}_{news_id}",
            ticker="MACRO",  # No specific ticker for macro events
            published_at=published_at,
            title=title,
            summary=None,  # NewsNow API doesn't provide summaries
            url=final_url if final_url else None,
            source=platform_name,
            collector="newsnow"
        )
