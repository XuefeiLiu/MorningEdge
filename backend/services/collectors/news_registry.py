"""
News source registry for managing collectors and configuration.
Inspired by TrendRadar's feed configuration system.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

from .base import BaseCollector

logger = logging.getLogger(__name__)


@dataclass
class NewsSourceConfig:
    """Configuration for a news source."""
    enabled: bool = True
    priority: int = 1  # Lower number = higher priority
    max_items_per_symbol: int = 50
    freshness_days: Optional[int] = None  # None = use global default
    reliability_score: float = 0.5  # 0.0 to 1.0
    name: str = ""
    source_type: str = "news"
    requires_api_key: bool = False
    extra_config: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.extra_config is None:
            self.extra_config = {}


class NewsSourceRegistry:
    """Registry to manage all news collectors and their configurations."""
    
    def __init__(self):
        self._collectors: Dict[str, BaseCollector] = {}
        self._configs: Dict[str, NewsSourceConfig] = {}
    
    def register(
        self,
        collector: BaseCollector,
        config: NewsSourceConfig
    ) -> None:
        """
        Register a news collector with its configuration.
        
        Args:
            collector: The collector instance
            config: Configuration for the collector
        """
        source_id = collector.name
        self._collectors[source_id] = collector
        self._configs[source_id] = config
        logger.info(f"Registered news source: {source_id} (priority={config.priority})")
    
    def get_collector(self, source_id: str) -> Optional[BaseCollector]:
        """Get a collector by source ID."""
        return self._collectors.get(source_id)
    
    def get_config(self, source_id: str) -> Optional[NewsSourceConfig]:
        """Get configuration for a source."""
        return self._configs.get(source_id)
    
    def get_enabled_collectors(self) -> List[BaseCollector]:
        """Get all enabled collectors, sorted by priority."""
        enabled = [
            collector for source_id, collector in self._collectors.items()
            if self._configs.get(source_id, NewsSourceConfig()).enabled
        ]
        # Sort by priority (lower number = higher priority)
        enabled.sort(key=lambda c: self._configs.get(c.name, NewsSourceConfig()).priority)
        return enabled
    
    def get_news_collectors(self) -> List[BaseCollector]:
        """Get all collectors that provide news (source_type='news' or 'multi')."""
        return [
            collector for collector in self.get_enabled_collectors()
            if self._configs.get(collector.name, NewsSourceConfig()).source_type in ("news", "multi")
        ]
    
    def is_enabled(self, source_id: str) -> bool:
        """Check if a source is enabled."""
        config = self._configs.get(source_id)
        return config.enabled if config else False
    
    def get_all_source_ids(self) -> List[str]:
        """Get all registered source IDs."""
        return list(self._collectors.keys())
    
    def get_source_metadata(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a source."""
        config = self._configs.get(source_id)
        if not config:
            return None
        
        collector = self._collectors.get(source_id)
        return {
            "id": source_id,
            "name": config.name or source_id,
            "enabled": config.enabled,
            "priority": config.priority,
            "reliability_score": config.reliability_score,
            "source_type": config.source_type,
            "is_available": collector.is_available if collector else False,
            "max_items_per_symbol": config.max_items_per_symbol,
            "freshness_days": config.freshness_days,
        }


# Global registry instance
news_registry = NewsSourceRegistry()
