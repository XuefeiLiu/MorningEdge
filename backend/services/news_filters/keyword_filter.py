"""
Keyword-based news relevance filter.
Checks if news items are relevant to a ticker using keyword matching.
"""
import logging
from typing import List
from datetime import datetime, timezone

from backend.models import NewsItem
from backend.config import DEFAULT_KEYWORDS, RELEVANCE_THRESHOLD
from .base import NewsFilter

logger = logging.getLogger(__name__)


class KeywordRelevanceFilter(NewsFilter):
    """
    Filters news items based on keyword matching and ticker relevance.
    Similar to DataFilter but focused on single-ticker relevance checking.
    """
    
    def __init__(
        self,
        keywords: List[str] = None,
        relevance_threshold: float = RELEVANCE_THRESHOLD
    ):
        """
        Initialize keyword relevance filter.
        
        Args:
            keywords: List of keywords to check for (default: from config)
            relevance_threshold: Minimum relevance score to include item (default: 0.3)
        """
        super().__init__("keyword")
        self.keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
        self.relevance_threshold = relevance_threshold
    
    async def filter(
        self,
        items: List[NewsItem],
        ticker: str
    ) -> List[NewsItem]:
        """
        Filter news items to only include those relevant to the ticker.
        
        Args:
            items: List of NewsItem objects to filter
            ticker: Stock ticker symbol to check relevance against
            
        Returns:
            Filtered list of NewsItem objects relevant to the ticker
        """
        if not items:
            return []
        
        ticker_normalized = self._normalize_ticker(ticker)
        filtered = []
        
        for item in items:
            relevance = self._calculate_relevance(item, ticker_normalized)
            
            if relevance >= self.relevance_threshold:
                filtered.append(item)
            else:
                logger.debug(
                    f"Filtered out: {item.title[:50]} "
                    f"(relevance: {relevance:.2f} < {self.relevance_threshold})"
                )
        
        logger.info(
            f"Keyword filter: {len(filtered)}/{len(items)} items relevant to {ticker}"
        )
        return filtered
    
    def _calculate_relevance(
        self,
        item: NewsItem,
        ticker: str
    ) -> float:
        """
        Calculate relevance score for a news item to a specific ticker.
        
        Scoring factors:
        - Ticker mention in title/summary: +0.4
        - Keyword matches: +0.1 per keyword (max 0.4)
        - Source reliability: +0.1 for known sources
        - Recency: +0.1 for items < 6 hours old
        
        Args:
            item: NewsItem to score
            ticker: Ticker symbol to check relevance against
            
        Returns:
            Relevance score (0.0 to 1.0)
        """
        score = 0.0
        text = self._extract_text(item).lower()
        ticker_lower = ticker.lower()
        
        # Ticker relevance - check if ticker appears in text or item ticker matches
        if ticker_lower in text or item.ticker.upper() == ticker:
            score += 0.4
        
        # Keyword matches
        keyword_matches = sum(1 for keyword in self.keywords if keyword in text)
        score += min(keyword_matches * 0.1, 0.4)
        
        # Source reliability bonus
        reliable_sources = [
            "reuters", "bloomberg", "wsj", "cnbc", "sec",
            "nasdaq", "alpha vantage", "fred", "financial times"
        ]
        if any(src in item.source.lower() for src in reliable_sources):
            score += 0.1
        
        # Recency bonus (items less than 6 hours old)
        try:
            item_time = item.published_at
            if item_time.tzinfo is None:
                item_time = item_time.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            age_hours = (now - item_time).total_seconds() / 3600
            if age_hours < 6:
                score += 0.1
        except Exception:
            pass  # Skip recency bonus if date parsing fails
        
        return min(score, 1.0)
