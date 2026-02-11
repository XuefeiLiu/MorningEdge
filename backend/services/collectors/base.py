"""
Base collector class for data sources.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Any, Optional, Literal
import logging

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all data collectors."""
    
    def __init__(self, name: str, source_type: Optional[Literal["news", "technical", "macro", "multi"]] = None):
        self.name = name
        self.is_available = True
        self._last_error: Optional[str] = None
        self.source_type = source_type or "multi"  # Default to multi-purpose
    
    @abstractmethod
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[Any]:
        """
        Collect data for the given symbols within the time window.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of the data collection window
            end_time: End of the data collection window
            
        Returns:
            List of collected data items
        """
        pass
    
    async def collect_news(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[Any]:
        """
        Optional method for collectors that only provide news.
        Default implementation delegates to collect().
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of the data collection window
            end_time: End of the data collection window
            
        Returns:
            List of news items
        """
        return await self.collect(symbols, start_time, end_time)
    
    def mark_unavailable(self, error: str) -> None:
        """Mark this collector as unavailable due to an error."""
        self.is_available = False
        self._last_error = error
        logger.warning(f"Collector {self.name} marked unavailable: {error}")
    
    def get_last_error(self) -> Optional[str]:
        """Get the last error message if any."""
        return self._last_error
