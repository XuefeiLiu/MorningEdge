"""
Gemini API collector for stock news.
Uses Google Gemini API to generate news items based on ticker and date range.
"""
import os
import re
import logging
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from hashlib import md5

from backend.models import NewsItem
from .base import BaseCollector
from .prompts import get_stock_news_prompt

logger = logging.getLogger(__name__)


def _parse_markdown_articles(content: str) -> List[Dict[str, Any]]:
    """
    Parse markdown-style response when Gemini returns *Title*/*Summary*/*Source*/*Date* instead of JSON.
    Splits by *Title:* and extracts title, summary, source, published_at per block.
    """
    articles = []
    # Split on *Title:* (with optional leading "N. " number)
    blocks = re.split(r"\n\s*\d*\.?\s*\*Title\*:\s*", content, flags=re.IGNORECASE)
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block or len(block) < 5:
            continue
        # Skip preamble (first segment before any *Title*: usually has no article structure)
        if i == 0 and ("*Summary*:" not in block and "*Source*:" not in block):
            continue
        # Title: first quoted string or first line
        first_line = block.split("\n")[0].strip()
        title_match = re.match(r'^["\']?(.+?)["\']?\s*$', first_line)
        if title_match:
            title = title_match.group(1).strip().strip('"').strip()
        else:
            title = first_line.strip('"').strip()
        if not title or len(title) < 3:
            continue
        # *Summary:* ... (until *Source:* or *Date:* or next block)
        summary = ""
        summary_m = re.search(r"\*Summary\*:\s*(.+?)(?=\s*\*Source\*:|\s*\*Date\*:|\s*\*Title\*:|\Z)", block, re.DOTALL | re.IGNORECASE)
        if summary_m:
            summary = summary_m.group(1).strip()
        # *Source:* ...
        source = ""
        source_m = re.search(r"\*Source\*:\s*([^\n*]+)", block, re.IGNORECASE)
        if source_m:
            source = source_m.group(1).strip()
        # *Date:* ...
        date_str = ""
        date_m = re.search(r"\*Date\*:\s*([^\n*]+)", block, re.IGNORECASE)
        if date_m:
            date_str = date_m.group(1).strip()
        articles.append({
            "title": title,
            "summary": summary or title,
            "source": source or "Gemini",
            "published_at": date_str or "",
            "url": "",
        })
    return articles

# Try to import Gemini (new SDK only)
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("Gemini package not installed. Install with: pip install google-genai")


class GeminiCollector(BaseCollector):
    """Collector for Google Gemini API news generation.
    Uses Google Search grounding (when available) to retrieve real-time online news,
    similar to OpenAI's web_search tool.
    """
    
    DEFAULT_MODEL = "gemini-3-flash-preview"
    DEFAULT_MAX_ITEMS = 10
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize Gemini collector.
        
        Args:
            api_key: Gemini API key
            model: Gemini model to use. If not provided, uses GEMINI_MODEL from config,
                   or falls back to DEFAULT_MODEL (gemini-3-flash-preview).
                   Examples: "gemini-3-flash-preview", "gemini-2.5-flash", etc.
        """
        super().__init__("gemini", source_type="news")
        
        if not GEMINI_AVAILABLE:
            self.mark_unavailable("Gemini package not installed")
            return
        
        # Get API key from parameter, environment variable, or config
        self.api_key = api_key
        if not self.api_key:
            self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            from dotenv import load_dotenv
            load_dotenv()
            self.api_key = os.getenv("GEMINI_API_KEY")
        
        # Get model from parameter, config, or use default
        if model:
            self.model = model
        else:
            from backend.config import GEMINI_MODEL
            self.model = GEMINI_MODEL or self.DEFAULT_MODEL
        
        if not self.api_key:
            self.mark_unavailable("GEMINI_API_KEY not configured (check .env file)")
            logger.warning("Gemini API key not found. Please set GEMINI_API_KEY in .env file")
        else:
            try:
                # Use new SDK (google-genai) - old google.generativeai is deprecated
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Using google-genai SDK (google.generativeai is deprecated)")
                logger.info("Gemini API key loaded successfully")
            except ImportError:
                self.mark_unavailable("google-genai package not installed. Install with: pip install google-genai")
                logger.error("google-genai package not available")
            except Exception as e:
                self.mark_unavailable(f"Failed to configure Gemini: {e}")
                logger.error(f"Failed to configure Gemini: {e}")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect news from Gemini API for symbols.
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects
        """
        if not self.is_available:
            logger.info(f"Gemini collector unavailable: {self._last_error}")
            return []
        
        if not GEMINI_AVAILABLE:
            return []
        
        news_items = []
        
        try:
            for symbol in symbols:
                symbol_news = await self._collect_for_symbol(
                    symbol, start_time, end_time
                )
                news_items.extend(symbol_news)
        
        except Exception as e:
            logger.error(f"Error in Gemini collection: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return news_items
    
    async def _collect_for_symbol(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Collect news for a single symbol using Gemini."""
        
        # Create the prompt using common prompt function
        prompt = get_stock_news_prompt(symbol=symbol)

        try:
            # Use new SDK (google-genai) with Google Search grounding
            response = await self._call_gemini_api(prompt, symbol)
            
            if not response:
                return []
            
            # Extract response content
            content = response.strip()
            logger.debug(f"Gemini raw response (first 500 chars): {content[:500]}")
            
            # Clean up the content - remove markdown code blocks if present
            if content.startswith("```json"):
                # Remove ```json and closing ```
                content = content[7:]  # Remove ```json
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            elif content.startswith("```"):
                # Remove generic code blocks
                lines = content.split("\n")
                if len(lines) > 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
                    content = "\n".join(lines[1:-1])
                content = content.strip()

            # If response is truncated from the start (e.g. begins mid-JSON), start from first { or [
            content_stripped = content.strip()
            if content_stripped and not content_stripped[0] in ("{", "["):
                i_brace = content_stripped.find("{")
                i_bracket = content_stripped.find("[")
                start = -1
                if i_brace >= 0 and i_bracket >= 0:
                    start = min(i_brace, i_bracket)
                elif i_brace >= 0:
                    start = i_brace
                elif i_bracket >= 0:
                    start = i_bracket
                if start >= 0:
                    content = content_stripped[start:]
                    logger.debug("Trimmed leading non-JSON from Gemini response")

            # Try to parse as JSON
            articles = []
            try:
                data = json.loads(content)
                # If it's a JSON object, look for common keys
                if isinstance(data, dict):
                    # Try common keys
                    articles = data.get("articles", data.get("news", data.get("items", data.get("data", []))))
                    if not articles and len(data) == 1:
                        # If only one key, use its value
                        articles = list(data.values())[0]
                        if not isinstance(articles, list):
                            articles = [articles] if articles else []
                else:
                    articles = data if isinstance(data, list) else []
                logger.debug(f"Parsed {len(articles)} articles from Gemini response")
            except json.JSONDecodeError as e:
                # If direct parse fails, try repair (truncated response) then extract array
                logger.warning(f"JSON parse error: {e}. Attempting to repair or extract JSON...")
                import re
                # 1) Try repairing truncated JSON (e.g. "Unterminated string" when model hit max tokens)
                repaired = content
                if "Unterminated" in str(e) or "Expecting" in str(e):
                    open_braces = repaired.count("{") - repaired.count("}")
                    open_brackets = repaired.count("[") - repaired.count("]")
                    repair_suffix = '"'
                    if open_braces > 0:
                        repair_suffix += "}" * open_braces
                    if open_brackets > 0:
                        repair_suffix += "]" * open_brackets
                    repaired = content.rstrip() + repair_suffix
                try:
                    data = json.loads(repaired)
                    if isinstance(data, list):
                        articles = data
                    elif isinstance(data, dict):
                        articles = data.get("articles", data.get("news", data.get("items", data.get("data", []))))
                        if not isinstance(articles, list):
                            articles = [articles] if articles else []
                    else:
                        articles = []
                    if articles:
                        logger.debug(f"Repaired truncated JSON: {len(articles)} articles")
                except json.JSONDecodeError:
                    articles = []
                # 2) If repair failed, truncate at last complete "}," (safe: only between array elements)
                if not articles and content.strip().startswith("["):
                    last_complete = content.rfind("},")
                    if last_complete >= 0:
                        truncated = content[: last_complete + 1] + "]"
                        try:
                            articles = json.loads(truncated)
                            logger.debug(f"Extracted {len(articles)} complete articles from truncated response")
                        except json.JSONDecodeError:
                            pass
                # 2b) Response truncated from start: content may be "{ ... }, { ... }" (array body without brackets)
                if not articles and content.strip().startswith("{"):
                    to_wrap = content.strip().rstrip(",").strip()
                    wrapped = "[" + to_wrap + "]"
                    try:
                        data = json.loads(wrapped)
                        if isinstance(data, list):
                            articles = data
                            logger.debug(f"Parsed {len(articles)} articles from response wrapped as array")
                    except json.JSONDecodeError:
                        last_complete = content.rfind("},")
                        if last_complete >= 0:
                            wrapped = "[" + content[: last_complete + 1] + "]"
                            try:
                                articles = json.loads(wrapped)
                                logger.debug(f"Extracted {len(articles)} articles from start-truncated response")
                            except json.JSONDecodeError:
                                pass
                # 3) If response is markdown-style (*Title*/*Summary*/*Source*/*Date*) instead of JSON
                if not articles and ("*Title*:" in content or "*Summary*:" in content or "*title*:" in content.lower()):
                    articles = _parse_markdown_articles(content)
                    if articles:
                        logger.debug(f"Parsed {len(articles)} articles from markdown-style response")
                if not articles:
                    logger.error(f"Failed to parse Gemini response as JSON: {e}")
                    logger.error(f"Response content (first 500 chars): {content[:500]}")
                    return []
            
            if not articles:
                logger.warning(f"Gemini returned empty articles list. Response: {content[:200]}")
                return []
            
            # Convert to NewsItem objects
            news_items = []
            for i, article in enumerate(articles):
                try:
                    news_item = self._dict_to_news_item(article, symbol, start_time, end_time)
                    if news_item:
                        news_items.append(news_item)
                    else:
                        logger.debug(f"Article {i+1} was filtered out (likely outside date range)")
                except Exception as e:
                    logger.warning(f"Error converting article {i+1} to NewsItem: {e}")
                    logger.debug(f"Article data: {article}")
            
            logger.info(f"Successfully converted {len(news_items)} articles to NewsItem objects for {symbol}")
            return news_items
        
        except Exception as e:
            logger.error(f"Error calling Gemini API for {symbol}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    async def _call_gemini_api(self, prompt: str, symbol: str) -> Optional[str]:
        """Call Gemini API using google-genai SDK with Google Search grounding for real-time news."""
        try:
            import asyncio
            from google import genai
            from google.genai import types
            from backend.config import GEMINI_MAX_TOKENS
            
            # Enable Google Search grounding (like OpenAI web_search) for live online news
            grounding_tool = types.Tool(google_search=types.GoogleSearch())
            config = types.GenerateContentConfig(
                temperature=0.9,
                max_output_tokens=GEMINI_MAX_TOKENS,
                tools=[grounding_tool],
            )
            
            # For async, use run_in_executor since new SDK might not have full async support
            loop = asyncio.get_event_loop()
            
            def generate():
                return self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
            
            response = await loop.run_in_executor(None, generate)
            
            # Extract text from response
            if hasattr(response, 'text'):
                return response.text
            elif hasattr(response, 'candidates') and response.candidates:
                if hasattr(response.candidates[0], 'content'):
                    parts = response.candidates[0].content.parts
                    if parts:
                        return parts[0].text
            else:
                logger.error(f"Unexpected response format from Gemini: {response}")
                return None
                
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _dict_to_news_item(
        self,
        item: Dict[str, Any],
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> Optional[NewsItem]:
        """Convert API response item (topic or article) to NewsItem."""
        # Topic-style: prefer topic, fallback to title
        title = (item.get("topic") or item.get("title") or "").strip()
        if not title:
            return None

        # URL: first from sources (array or comma-separated) or single url
        url_raw = item.get("url", "").strip()
        sources = item.get("sources")
        if sources:
            if isinstance(sources, list):
                url_raw = (sources[0] or "").strip() if sources else url_raw
            else:
                first = (sources or "").strip().split(",")[0].strip()
                if first:
                    url_raw = first
        url = url_raw or None

        # Parse published_at (single date or range "YYYY-MM-DD – YYYY-MM-DD"; use start of range)
        published_at_str = item.get("published_at", "")
        try:
            if published_at_str:
                # Range: take the first date
                date_part = published_at_str.strip()
                if " – " in date_part:
                    date_part = date_part.split(" – ")[0].strip()
                elif " - " in date_part:
                    date_part = date_part.split(" - ")[0].strip()
                if "T" in date_part:
                    published_at = datetime.fromisoformat(date_part.replace("Z", "+00:00"))
                elif len(date_part) >= 10:
                    published_at = datetime.strptime(date_part[:10], "%Y-%m-%d")
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

        # Filter by date range (with some tolerance for date-only entries)
        published_date = published_at.date()
        start_date = start_time.date()
        end_date = end_time.date()
        if not (start_date <= published_date <= end_date):
            logger.debug(f"Topic filtered out: published_at={published_at} (date: {published_date}) not in range [{start_date}, {end_date}]")
            return None

        # Generate unique ID
        news_id = md5(f"{title}{url or ''}{published_at_str}{symbol}".encode()).hexdigest()[:12]
        return NewsItem(
            id=f"gemini_{news_id}",
            ticker=symbol.upper(),
            published_at=published_at,
            title=title,
            summary=item.get("summary", "").strip() or None,
            url=url,
            source=item.get("source", "Gemini Generated").strip(),
            collector="gemini"
        )
