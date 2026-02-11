"""
News Aggregator service for multi-source news collection and deduplication.
Coordinates collection from multiple news sources per symbol.
"""
import logging
import time
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional
import asyncio

from backend.models import NewsItem
from backend.services.collectors.base import BaseCollector
from backend.services.collectors.news_registry import news_registry

logger = logging.getLogger(__name__)


class NewsAggregator:
    """Aggregates news from multiple sources per symbol."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize news aggregator.
        
        Args:
            config: Configuration dict with aggregation settings
        """
        self.config = config or {}
        self.deduplication_threshold = self.config.get("deduplication_threshold", 0.85)
        self.max_items_per_source = self.config.get("max_items_per_source", 50)
    
    async def collect_for_symbols(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from all enabled sources for symbols.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            Aggregated and deduplicated list of NewsItem objects
        """
        # Get all enabled news collectors
        collectors = news_registry.get_news_collectors()
        
        logger.info(f"NewsAggregator: Found {len(collectors)} collectors from registry")
        for c in collectors:
            logger.info(f"  - {c.name} (available={c.is_available})")
        
        if not collectors:
            logger.warning("No enabled news collectors found")
            return []
        
        # Filter to only available collectors
        available_collectors = [c for c in collectors if c.is_available]
        if len(available_collectors) < len(collectors):
            unavailable = [c.name for c in collectors if not c.is_available]
            logger.warning(f"Some collectors are unavailable: {unavailable}")
        
        collectors = available_collectors
        if not collectors:
            logger.warning("No available news collectors found")
            return []
        
        collector_names = [c.name for c in collectors]
        logger.info(f"Collecting news from {len(collectors)} sources for {len(symbols)} symbols: {collector_names}")
        
        # Log each collector's availability status
        for collector in collectors:
            config = news_registry.get_config(collector.name)
            logger.info(f"Collector {collector.name}: available={collector.is_available}, enabled={config.enabled if config else 'unknown'}, source_type={config.source_type if config else 'unknown'}")
        
        # Collect from all sources in parallel
        tasks = []
        task_collectors = {}  # Map task index to collector name for better logging
        for collector in collectors:
            task = self._collect_from_source(
                collector, symbols, start_time, end_time
            )
            task_collectors[len(tasks)] = collector.name
            tasks.append(task)
            logger.info(f"Created task for collector: {collector.name}")
        
        # Execute with global timeout (reduced to prevent hanging)
        global_timeout = min(self.config.get("global_timeout", 60.0), 40.0)  # Cap at 40s
        logger.info(f"Starting parallel collection with {len(tasks)} tasks, timeout={global_timeout}s")
        start_time_agg = time.monotonic()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=global_timeout
            )
            elapsed = time.monotonic() - start_time_agg
            logger.info(f"All {len(results)} collection tasks completed in {elapsed:.2f}s")
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start_time_agg
            logger.error(f"News aggregation timed out after {elapsed:.2f}s (limit was {global_timeout}s)")
            # Return empty results instead of exceptions to allow fallback
            results = [[] for _ in tasks]
        except asyncio.CancelledError as ce:
            elapsed = time.monotonic() - start_time_agg
            logger.error(f"News aggregation was cancelled after {elapsed:.2f}s: {ce}")
            raise  # Re-raise to propagate
        
        # Aggregate results
        all_news = []
        logger.info(f"Processing {len(results)} results from collectors")
        for i, result in enumerate(results):
            collector = collectors[i]
            logger.info(f"Processing result {i+1}/{len(results)} from {collector.name}: type={type(result)}, is_exception={isinstance(result, Exception)}")
            
            if isinstance(result, Exception):
                logger.error(f"Error collecting from {collector.name}: {result}")
                import traceback
                if hasattr(result, '__traceback__'):
                    logger.error(f"Traceback: {traceback.format_exception(type(result), result, result.__traceback__)}")
                continue
            
            if result:
                # Apply per-source limits (but not for NewsNow - show all items)
                config = news_registry.get_config(collector.name)
                if config and collector.name != "newsnow":  # Don't limit NewsNow items
                    max_items = config.max_items_per_symbol * len(symbols)
                    original_count = len(result)
                    result = result[:max_items]
                    if len(result) < original_count:
                        logger.info(f"Limited {collector.name} results from {original_count} to {len(result)} items")
                
                all_news.extend(result)
                logger.info(f"✓ Collected {len(result)} items from {collector.name} (type: {type(result)}, is_list: {isinstance(result, list)})")
                if len(result) > 0:
                    logger.info(f"  Sample titles: {[item.title[:50] for item in result[:3]]}")
            else:
                logger.warning(f"✗ No results from {collector.name} (returned empty list or None, type: {type(result)})")
        
        # Deduplicate across sources
        deduplicated = self._deduplicate(all_news)
        
        # Sort by relevance and source priority
        sorted_news = self._sort_news(deduplicated)
        
        logger.info(f"Aggregated {len(sorted_news)} unique news items from {len(collectors)} sources")
        
        return sorted_news
    
    async def _collect_from_source(
        self,
        collector: BaseCollector,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect news from a single source with per-collector timeout."""
        # Per-collector timeout (30s for most, 90s for NewsNow which queries multiple platforms)
        collector_timeout = 90.0 if collector.name == "newsnow" else 30.0
        
        try:
            logger.info(f"Collecting from {collector.name} (timeout={collector_timeout}s, has collect_news: {hasattr(collector, 'collect_news')})")
            
            # Wrap collection in a timeout
            async def _collect():
                # Use collect_news if available, otherwise use collect
                if hasattr(collector, 'collect_news'):
                    return await collector.collect_news(symbols, start_time, end_time)
                else:
                    return await collector.collect(symbols, start_time, end_time)
            
            try:
                result = await asyncio.wait_for(_collect(), timeout=collector_timeout)
            except asyncio.TimeoutError:
                logger.error(f"{collector.name} timed out after {collector_timeout}s")
                return []
            except asyncio.CancelledError as ce:
                logger.error(f"{collector.name} was cancelled: {ce}")
                raise  # Re-raise to propagate
            
            logger.info(f"{collector.name} returned: type={type(result)}, is_list={isinstance(result, list)}, is_dict={isinstance(result, dict)}")
            
            # Handle different return types
            if isinstance(result, dict):
                # Some collectors return dicts (e.g., Alpha Vantage)
                news_items = result.get("news", [])
                if isinstance(news_items, list):
                    logger.info(f"{collector.name}: Extracted {len(news_items)} news items from dict")
                    return news_items
                logger.warning(f"{collector.name}: Dict result has no 'news' key or news is not a list")
                return []
            elif isinstance(result, list):
                # Most news collectors return lists directly
                logger.info(f"{collector.name}: Returning {len(result)} items from list")
                return result
            else:
                logger.warning(f"{collector.name}: Unexpected result type: {type(result)}")
                return []
            
        except asyncio.CancelledError:
            raise  # Re-raise CancelledError
        except Exception as e:
            logger.error(f"Error collecting from {collector.name}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def _deduplicate(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """
        Deduplicate news items across sources.
        Language-aware: Don't deduplicate across languages.
        """
        from difflib import SequenceMatcher
        from hashlib import md5
        
        seen_hashes: set = set()
        seen_titles: List[str] = []
        unique_items: List[NewsItem] = []
        
        # Group by language for language-aware deduplication
        by_language: Dict[Optional[str], List[NewsItem]] = {}
        for item in news_items:
            lang = item.language
            if lang not in by_language:
                by_language[lang] = []
            by_language[lang].append(item)
        
        # Deduplicate within each language group
        for lang, lang_items in by_language.items():
            for item in lang_items:
                # Check exact hash duplicate
                content_hash = md5(
                    f"{item.title}{item.url}".encode()
                ).hexdigest()
                
                if content_hash in seen_hashes:
                    continue
                
                # Check similar title (fuzzy matching) within same language
                title_lower = item.title.lower()
                is_duplicate = False
                for seen_title in seen_titles:
                    similarity = SequenceMatcher(
                        None, title_lower, seen_title
                    ).ratio()
                    if similarity >= self.deduplication_threshold:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    seen_hashes.add(content_hash)
                    seen_titles.append(title_lower)
                    unique_items.append(item)
        
        return unique_items
    
    def _sort_news(self, news_items: List[NewsItem]) -> List[NewsItem]:
        """
        Sort news items by relevance and source priority.
        """
        def sort_key(item: NewsItem) -> tuple:
            # Get source priority
            config = news_registry.get_config(item.source.split("-")[0])  # Handle "NewsNow-platform" format
            priority = config.priority if config else 999
            
            # Sort by: priority (ascending), published_at (descending)
            return (
                priority,
                -item.published_at.timestamp() if item.published_at else 0  # Negative for descending
            )
        
        return sorted(news_items, key=sort_key)
