"""
Base RSS collector class for all RSS-based news sources.
Inspired by TrendRadar's RSSParser.
"""
import feedparser
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from hashlib import md5
import asyncio
from concurrent.futures import ThreadPoolExecutor
import re
import html

from backend.models import NewsItem, Category, ImpactLevel
from .base import BaseCollector

logger = logging.getLogger(__name__)


class RSSParser:
    """Parser for RSS 2.0, Atom, and JSON Feed formats."""
    
    def __init__(self, max_summary_length: int = 500):
        """
        Initialize parser.
        
        Args:
            max_summary_length: Maximum length for summaries
        """
        self.max_summary_length = max_summary_length
    
    def parse(self, content: str, feed_url: str = "") -> List[Dict[str, Any]]:
        """
        Parse RSS/Atom/JSON Feed content.
        
        Args:
            content: Feed content (XML or JSON)
            feed_url: Feed URL (for error messages)
            
        Returns:
            List of parsed items with: title, url, published_at, summary, author
        """
        # Try JSON Feed first
        if self._is_json_feed(content):
            return self._parse_json_feed(content, feed_url)
        
        # Use feedparser for RSS/Atom
        feed = feedparser.parse(content)
        
        if feed.bozo and not feed.entries:
            logger.warning(f"Could not parse RSS feed ({feed_url}): {feed.bozo_exception}")
            return []
        
        items = []
        for entry in feed.entries:
            item = self._parse_entry(entry)
            if item:
                items.append(item)
        
        return items
    
    def _is_json_feed(self, content: str) -> bool:
        """Check if content is JSON Feed format."""
        content = content.strip()
        if not content.startswith("{"):
            return False
        
        try:
            import json
            data = json.loads(content)
            version = data.get("version", "")
            return "jsonfeed.org" in version
        except (json.JSONDecodeError, TypeError):
            return False
    
    def _parse_json_feed(self, content: str, feed_url: str = "") -> List[Dict[str, Any]]:
        """Parse JSON Feed 1.1 format."""
        try:
            import json
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON Feed parse failed ({feed_url}): {e}")
            return []
        
        items_data = data.get("items", [])
        if not items_data:
            return []
        
        items = []
        for item_data in items_data:
            item = self._parse_json_feed_item(item_data)
            if item:
                items.append(item)
        
        return items
    
    def _parse_json_feed_item(self, item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a single JSON Feed item."""
        title = item_data.get("title", "")
        if not title:
            content_text = item_data.get("content_text", "")
            if content_text:
                title = content_text[:100] + ("..." if len(content_text) > 100 else "")
        
        title = self._clean_text(title)
        if not title:
            return None
        
        url = item_data.get("url", "") or item_data.get("external_url", "")
        
        # Parse published date
        published_at = None
        date_str = item_data.get("date_published") or item_data.get("date_modified")
        if date_str:
            published_at = self._parse_iso_date(date_str)
        
        # Summary
        summary = item_data.get("summary", "")
        if not summary:
            content_text = item_data.get("content_text", "")
            content_html = item_data.get("content_html", "")
            summary = content_text or self._clean_text(content_html)
        
        if summary:
            summary = self._clean_text(summary)
            if len(summary) > self.max_summary_length:
                summary = summary[:self.max_summary_length] + "..."
        
        # Author
        author = None
        authors = item_data.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if isinstance(a, dict) and a.get("name")]
            if names:
                author = ", ".join(names)
        
        return {
            "title": title,
            "url": url,
            "published_at": published_at,
            "summary": summary or None,
            "author": author,
        }
    
    def _parse_iso_date(self, date_str: str) -> Optional[datetime]:
        """Parse ISO 8601 date format."""
        if not date_str:
            return None
        
        try:
            date_str = date_str.replace("Z", "+00:00")
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None
    
    def _parse_entry(self, entry: Any) -> Optional[Dict[str, Any]]:
        """Parse a single RSS/Atom entry."""
        title = self._clean_text(entry.get("title", ""))
        if not title:
            return None
        
        url = entry.get("link", "")
        if not url:
            links = entry.get("links", [])
            for link in links:
                if link.get("rel") == "alternate" or link.get("type", "").startswith("text/html"):
                    url = link.get("href", "")
                    break
            if not url and links:
                url = links[0].get("href", "")
        
        published_at = self._parse_date(entry)
        summary = self._parse_summary(entry)
        author = self._parse_author(entry)
        
        return {
            "title": title,
            "url": url,
            "published_at": published_at,
            "summary": summary,
            "author": author,
        }
    
    def _clean_text(self, text: str) -> str:
        """Clean HTML and normalize text."""
        if not text:
            return ""
        
        # Decode HTML entities
        text = html.unescape(text)
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def _parse_date(self, entry: Any) -> Optional[datetime]:
        """Parse publication date from entry."""
        # feedparser automatically parses dates to published_parsed
        date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        
        if date_struct:
            try:
                return datetime(*date_struct[:6])
            except (ValueError, TypeError):
                pass
        
        # Try manual parsing
        date_str = entry.get("published") or entry.get("updated")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                pass
            
            # Try ISO format
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        
        return None
    
    def _parse_summary(self, entry: Any) -> Optional[str]:
        """Parse summary/description from entry."""
        summary = entry.get("summary") or entry.get("description", "")
        
        if not summary:
            content = entry.get("content", [])
            if content and isinstance(content, list):
                summary = content[0].get("value", "")
        
        if not summary:
            return None
        
        summary = self._clean_text(summary)
        
        if len(summary) > self.max_summary_length:
            summary = summary[:self.max_summary_length] + "..."
        
        return summary
    
    def _parse_author(self, entry: Any) -> Optional[str]:
        """Parse author from entry."""
        author = entry.get("author")
        if author:
            return self._clean_text(author)
        
        author = entry.get("dc_creator")
        if author:
            return self._clean_text(author)
        
        authors = entry.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if a.get("name")]
            if names:
                return ", ".join(names)
        
        return None


class RSSCollector(BaseCollector):
    """Base class for all RSS-based news collectors."""
    
    def __init__(
        self,
        name: str,
        feed_urls: List[str],
        config: Optional[Dict[str, Any]] = None,
        default_language: str = "en"
    ):
        """
        Initialize RSS collector.
        
        Args:
            name: Collector name
            feed_urls: List of RSS feed URLs
            config: Optional configuration dict
            default_language: Default language for news items ("en" or "zh")
        """
        super().__init__(name, source_type="news")
        self.feed_urls = feed_urls
        self.config = config or {}
        self.parser = RSSParser(
            max_summary_length=self.config.get("max_summary_length", 500)
        )
        self.default_language = default_language
        self._executor = ThreadPoolExecutor(max_workers=4)
        self.max_age_days = self.config.get("max_age_days")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from RSS feeds.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects
        """
        news_items = []
        
        try:
            loop = asyncio.get_running_loop()
            tasks = []
            
            # Create tasks for each feed URL and symbol combination
            for feed_url in self.feed_urls:
                for symbol in symbols:
                    task = loop.run_in_executor(
                        self._executor,
                        self._fetch_feed,
                        feed_url,
                        symbol,
                        start_time,
                        end_time
                    )
                    tasks.append(task)
            
            # Execute with timeout
            timeout = self.config.get("timeout", 15.0)
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout
            )
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Error fetching RSS feed: {result}")
                    continue
                news_items.extend(result)
            
        except asyncio.TimeoutError:
            logger.warning(f"RSS collection timed out for {self.name}")
        except Exception as e:
            logger.error(f"Error in RSS collection for {self.name}: {e}")
        
        return news_items
    
    def _fetch_feed(
        self,
        feed_url: str,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Fetch and parse RSS feed (synchronous, runs in executor).
        
        Args:
            feed_url: RSS feed URL (may contain {symbol} placeholder)
            symbol: Stock symbol
            start_time: Start time window
            end_time: End time window
            
        Returns:
            List of NewsItem objects
        """
        news_items = []
        
        # Replace {symbol} placeholder if present
        actual_url = feed_url.replace("{symbol}", symbol)
        
        try:
            # Fetch feed
            feed_content = self._fetch_feed_content(actual_url)
            if not feed_content:
                return news_items
            
            # Parse feed
            parsed_items = self.parser.parse(feed_content, actual_url)
            
            # Convert to NewsItem
            for item in parsed_items:
                news_item = self._item_to_news_item(item, symbol, start_time, end_time)
                if news_item:
                    news_items.append(news_item)
            
        except Exception as e:
            logger.error(f"Error fetching RSS feed {actual_url} for {symbol}: {e}")
        
        return news_items
    
    def _fetch_feed_content(self, url: str) -> Optional[str]:
        """Fetch feed content (synchronous, runs in executor)."""
        try:
            import httpx
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, headers={
                    "User-Agent": "Morning Edge RSS Reader"
                })
                response.raise_for_status()
                return response.text
        except Exception as e:
            logger.error(f"Error fetching feed URL {url}: {e}")
            return None
    
    def _item_to_news_item(
        self,
        item: Dict[str, Any],
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> Optional[NewsItem]:
        """
        Convert parsed RSS item to NewsItem.
        
        Args:
            item: Parsed RSS item dict
            symbol: Stock symbol
            start_time: Start time window
            end_time: End time window
            
        Returns:
            NewsItem or None if filtered out
        """
        title = item.get("title", "")
        if not title:
            return None
        
        # Parse published date
        published_at = item.get("published_at")
        if not published_at:
            published_at = datetime.utcnow()
        else:
            # Remove timezone for comparison
            if hasattr(published_at, 'replace'):
                published_at = published_at.replace(tzinfo=None)
        
        # Apply time window filter
        if published_at < start_time.replace(tzinfo=None) or published_at > end_time.replace(tzinfo=None):
            return None
        
        # Apply freshness filter
        if self.max_age_days:
            age_days = (datetime.utcnow() - published_at).days
            if age_days > self.max_age_days:
                return None
        
        # Generate unique ID
        url = item.get("url", "")
        news_id = md5(f"{url}{title}".encode()).hexdigest()[:12]
        
        # Detect language (simple check for Chinese characters)
        language = self._detect_language(title + (item.get("summary") or ""))
        
        return NewsItem(
            id=f"{self.name}_{news_id}",
            ticker=symbol,
            published_at=published_at,
            title=title,
            summary=item.get("summary"),
            url=url,
            source=self.name,
            collector=self.name
        )
    
    def _detect_language(self, text: str) -> Optional[str]:
        """
        Simple language detection.
        Checks for Chinese characters, otherwise defaults to configured language.
        """
        if not text:
            return self.default_language
        
        # Check for Chinese characters (CJK Unified Ideographs)
        if re.search(r'[\u4e00-\u9fff]', text):
            return "zh"
        
        return self.default_language
