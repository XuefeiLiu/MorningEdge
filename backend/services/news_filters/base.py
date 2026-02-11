"""
Base filter interface for news filtering.
"""
import logging
from abc import ABC, abstractmethod
from typing import List
from datetime import datetime

from backend.models import NewsItem

logger = logging.getLogger(__name__)


class NewsFilter(ABC):
    """
    Abstract base class for news filters.
    All filters should implement the filter() method to check relevance to a ticker.
    """
    
    def __init__(self, name: str):
        """
        Initialize the filter.
        
        Args:
            name: Name identifier for this filter
        """
        self.name = name
    
    @abstractmethod
    async def filter(
        self,
        items: List[NewsItem],
        ticker: str
    ) -> List[NewsItem]:
        """
        Filter news items to only include those relevant to the given ticker.
        
        Args:
            items: List of NewsItem objects to filter
            ticker: Stock ticker symbol to check relevance against
            
        Returns:
            Filtered list of NewsItem objects relevant to the ticker
        """
        pass
    
    async def is_relevant(
        self,
        item: NewsItem,
        ticker: str
    ) -> bool:
        """
        Check if a single news item is relevant to a ticker.
        Default implementation filters a single-item list.
        
        Args:
            item: NewsItem to check
            ticker: Stock ticker symbol
            
        Returns:
            True if relevant, False otherwise
        """
        filtered = await self.filter([item], ticker)
        return len(filtered) > 0
    
    def _extract_text(self, item: NewsItem) -> str:
        """
        Extract searchable text from a NewsItem.
        
        Args:
            item: NewsItem object
            
        Returns:
            Combined title and summary text
        """
        text_parts = [item.title]
        if item.summary:
            text_parts.append(item.summary)
        return " ".join(text_parts)
    
    def _normalize_ticker(self, ticker: str) -> str:
        """
        Normalize ticker symbol for comparison.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Uppercase ticker symbol
        """
        return ticker.upper().strip()
