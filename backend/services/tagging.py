"""
Impact scoring and category tagging services.
"""
import re
import logging
from datetime import datetime
from typing import List, Any, Dict
from collections import defaultdict

from backend.config import HIGH_IMPACT_KEYWORDS, MEDIUM_IMPACT_KEYWORDS
from backend.models import (
    NewsItem, MacroEvent, SECFiling, SentimentData,
    ImpactLevel, Category
)

logger = logging.getLogger(__name__)


class ImpactTagger:
    """Tags data items with impact levels based on content analysis."""
    
    def __init__(
        self,
        high_keywords: List[str] = None,
        medium_keywords: List[str] = None
    ):
        self.high_keywords = [k.lower() for k in (high_keywords or HIGH_IMPACT_KEYWORDS)]
        self.medium_keywords = [k.lower() for k in (medium_keywords or MEDIUM_IMPACT_KEYWORDS)]
    
    def tag_news(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """
        Tag news items with impact levels.
        
        Impact is determined by:
        - Keyword matching (high/medium/low)
        - Source credibility
        - Number of symbols affected
        
        Note: NewsItem model doesn't have impact_level field, so we just return the items.
        """
        # NewsItem doesn't have impact_level field, so we don't set it
        return news_items
    
    def _calculate_news_impact(self, item: NewsItem) -> ImpactLevel:
        """Calculate impact level for a news item."""
        text = f"{item.title} {item.summary or ''}".lower()
        
        # Check for high-impact keywords
        for keyword in self.high_keywords:
            if keyword in text:
                return ImpactLevel.HIGH
        
        # Check for medium-impact keywords
        for keyword in self.medium_keywords:
            if keyword in text:
                return ImpactLevel.MEDIUM
        
        # Note: NewsItem has single ticker, not multiple symbols
        # This check is not applicable for NewsItem
        
        # Default to low impact for news items
        return ImpactLevel.LOW
    
    def tag_macro_events(self, events: List[MacroEvent]) -> List[MacroEvent]:
        """Tag macro events (usually pre-tagged, validate here)."""
        for event in events:
            # Validate/adjust impact based on content
            text = f"{event.title} {event.description or ''}".lower()
            
            if any(k in text for k in ["fed", "rate", "inflation", "gdp", "jobs"]):
                event.impact_level = ImpactLevel.HIGH
            elif any(k in text for k in ["housing", "retail", "consumer"]):
                event.impact_level = ImpactLevel.MEDIUM
        
        return events
    
    def tag_filings(self, filings: List[SECFiling]) -> List[SECFiling]:
        """Tag SEC filings based on form type."""
        high_impact_forms = ["8-K", "10-K", "S-1", "SC 13D"]
        medium_impact_forms = ["10-Q", "4", "SC 13G", "424B"]
        
        for filing in filings:
            if any(filing.form_type.startswith(f) for f in high_impact_forms):
                filing.impact_level = ImpactLevel.HIGH
            elif any(filing.form_type.startswith(f) for f in medium_impact_forms):
                filing.impact_level = ImpactLevel.MEDIUM
            else:
                filing.impact_level = ImpactLevel.LOW
        
        return filings


class CategoryTagger:
    """Tags data items with categories."""
    
    # Category detection patterns
    CATEGORY_PATTERNS = {
        Category.COMPANY_NEWS: [
            r"earnings", r"revenue", r"profit", r"loss", r"ceo",
            r"announces", r"partnership", r"acquisition", r"merger",
            r"product", r"launch", r"lawsuit", r"settlement"
        ],
        Category.MACRO_EVENT: [
            r"fed", r"interest rate", r"inflation", r"gdp",
            r"unemployment", r"jobs report", r"consumer price",
            r"trade", r"tariff", r"central bank"
        ],
        Category.TECHNICAL_DATA: [
            r"price", r"volume", r"support", r"resistance",
            r"moving average", r"breakout", r"volatility"
        ],
        Category.MARKET_SENTIMENT: [
            r"sentiment", r"bullish", r"bearish", r"fear",
            r"greed", r"trending", r"social media", r"reddit",
            r"twitter", r"analyst rating"
        ]
    }
    
    def __init__(self):
        # Compile patterns for efficiency
        self._compiled_patterns = {
            cat: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cat, patterns in self.CATEGORY_PATTERNS.items()
        }
    
    def tag_news(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """Tag news items with categories.
        
        Note: NewsItem model doesn't have category field, so we just return the items.
        """
        # NewsItem doesn't have category field, so we don't set it
        return news_items
    
    def _detect_category(self, text: str) -> Category:
        """Detect the most likely category for text."""
        scores: Dict[Category, int] = defaultdict(int)
        
        for category, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    scores[category] += 1
        
        if not scores:
            return Category.COMPANY_NEWS  # Default
        
        return max(scores, key=scores.get)
    
    def categorize_all(
        self,
        news: List[NewsItem],
        macro: List[MacroEvent],
        technical: List[Any],
        sentiment: List[SentimentData]
    ) -> Dict[Category, List[Any]]:
        """
        Organize all data by category.
        
        Returns a dictionary with items grouped by category.
        """
        categorized = {
            Category.COMPANY_NEWS: [],
            Category.MACRO_EVENT: [],
            Category.TECHNICAL_DATA: [],
            Category.MARKET_SENTIMENT: []
        }
        
        # Tag and add news
        # NewsItem doesn't have category field, so we categorize based on source
        for item in self.tag_news(news):
            # Check if it's a NewsNow source (macro event) or regular company news
            if item.source.startswith("NewsNow-"):
                categorized[Category.MACRO_EVENT].append(item)
            else:
                categorized[Category.COMPANY_NEWS].append(item)
        
        # Macro events are always macro
        categorized[Category.MACRO_EVENT].extend(macro)
        
        # Technical data
        categorized[Category.TECHNICAL_DATA].extend(technical)
        
        # Sentiment data
        categorized[Category.MARKET_SENTIMENT].extend(sentiment)
        
        return categorized


class DataSorter:
    """Sorts data by impact level and other criteria."""
    
    IMPACT_ORDER = {
        ImpactLevel.HIGH: 0,
        ImpactLevel.MEDIUM: 1,
        ImpactLevel.LOW: 2
    }
    
    def sort_by_impact(self, items: List[Any]) -> List[Any]:
        """Sort items by impact level (high first)."""
        return sorted(
            items,
            key=lambda x: (
                self.IMPACT_ORDER.get(
                    getattr(x, "impact_level", ImpactLevel.LOW),
                    2
                ),
                # Secondary sort by time (most recent first)
                -self._get_timestamp(x)
            )
        )
    
    def _get_timestamp(self, item: Any) -> float:
        """Get timestamp from item for sorting."""
        for attr in ["published_at", "event_time", "filed_date", "timestamp"]:
            val = getattr(item, attr, None)
            if val:
                return val.timestamp()
        return 0
    
    def sort_by_relevance(self, items: List[Any]) -> List[Any]:
        """Sort items by published date (newest first)."""
        return sorted(
            items,
            key=lambda x: x.published_at if hasattr(x, 'published_at') and x.published_at else datetime.min,
            reverse=True
        )
    
    def get_high_impact_count(self, items: List[Any]) -> int:
        """Count high-impact items."""
        return sum(
            1 for item in items
            if getattr(item, "impact_level", None) == ImpactLevel.HIGH
        )
