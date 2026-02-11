"""
Nasdaq RSS feed collector for press releases and company news.
Free public RSS feeds.
Inherits from RSSCollector base class.
"""
import logging
from typing import List
from datetime import datetime

from backend.config import NASDAQ_RSS_BASE_URL
from backend.models import NewsItem
from .rss_collector import RSSCollector

logger = logging.getLogger(__name__)


class NasdaqRSSCollector(RSSCollector):
    """Collector for Nasdaq RSS press release feeds."""
    
    def __init__(self):
        # Nasdaq RSS feed URL pattern with {symbol} placeholder
        feed_urls = [f"{NASDAQ_RSS_BASE_URL}?symbol={{symbol}}"]
        super().__init__(
            name="nasdaq_rss",
            feed_urls=feed_urls,
            config={"max_summary_length": 500, "timeout": 15.0},
            default_language="en"  # Nasdaq is English
        )
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect press releases from Nasdaq RSS for symbols."""
        news_items = await super().collect(symbols, start_time, end_time)
        
        # Limit entries per symbol (Nasdaq-specific)
        limited_items = []
        items_per_symbol = {}
        for item in news_items:
            symbol = item.ticker
            if symbol not in items_per_symbol:
                items_per_symbol[symbol] = 0
            if items_per_symbol[symbol] < 20:  # Limit to 20 per symbol
                limited_items.append(item)
                items_per_symbol[symbol] += 1
        
        return limited_items
