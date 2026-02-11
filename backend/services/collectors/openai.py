"""
OpenAI API collector for stock news.
Uses OpenAI API to generate news items based on ticker and date range.
"""
import os
import logging
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from hashlib import md5

from backend.models import NewsItem
from .base import BaseCollector
from .prompts import get_stock_news_prompt, get_system_message

logger = logging.getLogger(__name__)

# Try to import OpenAI
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not installed. Install with: pip install openai")


class OpenAICollector(BaseCollector):
    """Collector for OpenAI API news generation."""
    
    DEFAULT_MODEL = "gpt-5.2"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize OpenAI collector.
        
        Args:
            api_key: OpenAI API key
            model: OpenAI model to use (default: gpt-4o-mini)
        """
        super().__init__("openai", source_type="news")
        
        if not OPENAI_AVAILABLE:
            self.mark_unavailable("OpenAI package not installed")
            return
        
        # Get API key from parameter, environment variable, or config
        self.api_key = api_key
        if not self.api_key:
            self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            from dotenv import load_dotenv
            load_dotenv()
            self.api_key = os.getenv("OPENAI_API_KEY")
        
        self.model = model or self.DEFAULT_MODEL
        
        if not self.api_key:
            self.mark_unavailable("OPENAI_API_KEY not configured (check .env file)")
            logger.warning("OpenAI API key not found. Please set OPENAI_API_KEY in .env file")
        else:
            try:
                self.client = AsyncOpenAI(api_key=self.api_key) if OPENAI_AVAILABLE else None
                logger.info("OpenAI API key loaded successfully")
            except Exception as e:
                self.mark_unavailable(f"Failed to configure OpenAI: {e}")
                logger.error(f"Failed to configure OpenAI: {e}")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from OpenAI API for symbols.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects
        """
        if not self.is_available:
            logger.info(f"OpenAI collector unavailable: {self._last_error}")
            return []
        
        if not OPENAI_AVAILABLE:
            return []
        
        news_items = []
        
        try:
            for symbol in symbols:
                symbol_news = await self._collect_for_symbol(
                    symbol, start_time, end_time
                )
                news_items.extend(symbol_news)
        
        except Exception as e:
            logger.error(f"Error in OpenAI collection: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return news_items
    
    async def _collect_for_symbol(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect news for a single symbol using OpenAI."""
        
        # Create the prompt using common prompt function (no date range needed)
        prompt = get_stock_news_prompt(symbol=symbol)

        try:
            # Use OpenAI API
            if not hasattr(self, 'client') or self.client is None:
                self.client = AsyncOpenAI(api_key=self.api_key)
            
            # Use Responses API with web_search tool
            if not hasattr(self.client, 'responses'):
                raise AttributeError("Responses API not available")
            
            response = await self.client.responses.create(
                model=self.model,
                tools=[{"type": "web_search"}],
                tool_choice={"type": "web_search"},
                input=f"{get_system_message()}\n\n{prompt}"
            )
            
            # Extract response content from Responses API.
            # response.output = [ResponseFunctionWebSearch(type='web_search_call'), ..., ResponseOutputMessage(type='message', content=...)]
            # We want the ResponseOutputMessage; its content is list of ResponseOutputText or single with .text.
            content = None
            if hasattr(response, "output") and response.output and isinstance(response.output, list):
                for item in response.output:
                    if getattr(item, "type", None) != "message":
                        continue
                    # ResponseOutputMessage: get .content (list of ResponseOutputText or single)
                    msg_content = getattr(item, "content", None)
                    if not msg_content:
                        if hasattr(item, "text") and item.text:
                            content = item.text
                        break
                    if isinstance(msg_content, list):
                        text_parts = [c.text for c in msg_content if getattr(c, "text", None)]
                        content = " ".join(text_parts) if text_parts else None
                    elif hasattr(msg_content, "text"):
                        content = msg_content.text or None
                    else:
                        content = str(msg_content)
                    if content:
                        break
            if not content:
                logger.warning("Could not extract content from Responses API; response.output=%s", getattr(response, "output", None))
                raise ValueError("Could not extract content from Responses API")
            if not isinstance(content, str):
                content = getattr(content, "text", None) or str(content)
            
            # Clean up the content - remove markdown code blocks if present
            if isinstance(content, str) and content.startswith("```json"):
                # Remove ```json and closing ```
                content = content[7:]  # Remove ```json
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            elif isinstance(content, str) and content.startswith("```"):
                # Remove generic code blocks
                lines = content.split("\n")
                if len(lines) > 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
                    content = "\n".join(lines[1:-1])
                content = content.strip()
            
            # Try to parse as JSON. API returns a list of article dicts: [{'title', 'summary', 'url', 'source', 'published_at'}, ...]
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    articles = data
                elif isinstance(data, dict):
                    articles = data.get("articles") or data.get("news") or data.get("items") or data.get("data")
                    if not isinstance(articles, list):
                        articles = list(data.values())[0] if len(data) == 1 else []
                    if not isinstance(articles, list):
                        articles = [articles] if articles else []
                else:
                    articles = []
            except json.JSONDecodeError:
                # If direct parse fails, try to extract JSON array from text
                import re
                # Try to find JSON array
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    try:
                        articles = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        logger.error(f"Failed to parse extracted JSON: {content[:200]}")
                        return []
                else:
                    logger.error(f"Failed to parse OpenAI response as JSON: {content[:200]}")
                    return []
            
            # Convert to NewsItem objects
            news_items = []
            for article in articles:
                news_item = self._dict_to_news_item(article, symbol, start_time, end_time)
                if news_item:
                    news_items.append(news_item)
            
            return news_items
        
        except Exception as e:
            logger.error(f"Error calling OpenAI API for {symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _dict_to_news_item(
        self,
        item: Dict[str, Any],
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> Optional[NewsItem]:
        """Convert API response item to NewsItem.
        Expects item: {'title', 'summary', 'url', 'source', 'published_at'} (published_at: YYYY-MM-DD or ISO with T).
        """
        title = (item.get("title") or "").strip()
        if not title:
            return None
        
        # Parse published_at (e.g. '2026-01-28T23:55:28' or '2026-01-28')
        published_at_str = item.get("published_at") or ""
        try:
            if published_at_str:
                # Try different date formats
                if "T" in published_at_str:
                    published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                elif len(published_at_str) == 10:  # YYYY-MM-DD
                    published_at = datetime.strptime(published_at_str, "%Y-%m-%d")
                    # Set to noon UTC for date-only entries
                    published_at = published_at.replace(hour=12, minute=0, second=0)
                else:
                    published_at = datetime.now(timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)
        except (ValueError, TypeError):
            published_at = datetime.now(timezone.utc)
        
        # Ensure timezone-aware
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        
        # Generate unique ID
        url = item.get("url", "")
        news_id = md5(f"{title}{url}{published_at_str}{symbol}".encode()).hexdigest()[:12]
        
        return NewsItem(
            id=f"openai_{news_id}",
            ticker=symbol.upper(),
            published_at=published_at,
            title=title,
            summary=(item.get("summary") or "").strip() or None,
            url=(item.get("url") or "").strip() or None,
            source=(item.get("source") or "OpenAI Generated").strip(),
            collector="openai"
        )
