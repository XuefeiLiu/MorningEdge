"""
Gemini-based news relevance filter.
Uses Google Gemini API to determine if news items are relevant to a ticker.
"""
import os
import logging
import json
from typing import List, Optional

from backend.models import NewsItem
from backend.config import GEMINI_API_KEY, GEMINI_MODEL
from .base import NewsFilter
from .keyword_filter import KeywordRelevanceFilter

logger = logging.getLogger(__name__)

# Try to import Gemini
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
    USE_NEW_SDK = False
except ImportError:
    try:
        from google import genai
        GEMINI_AVAILABLE = True
        USE_NEW_SDK = True
    except ImportError:
        GEMINI_AVAILABLE = False
        USE_NEW_SDK = False
        logger.warning("Gemini package not installed. GeminiFilter will use keyword fallback.")


class GeminiFilter(NewsFilter):
    """
    Filters news items using Google Gemini API to check relevance to a ticker.
    Falls back to keyword filtering if Gemini is unavailable.
    """
    
    DEFAULT_MODEL = "gemini-2.0-flash-exp"
    DEFAULT_BATCH_SIZE = 10
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        use_fallback: bool = True
    ):
        """
        Initialize Gemini filter.
        
        Args:
            api_key: Gemini API key (default: from config)
            model: Gemini model to use (default: from config or gemini-2.0-flash-exp)
            batch_size: Number of items to process per API call (default: 10)
            use_fallback: Whether to fall back to keyword filter if Gemini fails (default: True)
        """
        super().__init__("gemini")
        
        self.use_ai = GEMINI_AVAILABLE and (api_key or GEMINI_API_KEY)
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or GEMINI_MODEL or self.DEFAULT_MODEL
        self.batch_size = batch_size
        self.use_fallback = use_fallback
        self.use_new_sdk = USE_NEW_SDK
        
        if self.use_ai:
            try:
                if self.use_new_sdk:
                    genai.configure(api_key=self.api_key)
                else:
                    genai.configure(api_key=self.api_key)
                logger.info(f"GeminiFilter initialized with model: {self.model}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self.use_ai = False
        else:
            if not GEMINI_AVAILABLE:
                logger.warning("Gemini package not available, will use keyword fallback")
            elif not self.api_key:
                logger.warning("Gemini API key not configured, will use keyword fallback")
        
        # Initialize fallback filter
        if self.use_fallback:
            self.fallback_filter = KeywordRelevanceFilter()
        else:
            self.fallback_filter = None
    
    async def _remove_duplicate_titles(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        Remove duplicate and near-duplicate news items based on title.
        Uses LLM to detect near-duplicates (titles that are almost the same with small differences).
        Keeps the first occurrence of each unique title.
        
        Args:
            items: List of NewsItem objects
            
        Returns:
            List of NewsItem objects with duplicate titles removed
        """
        if not items:
            return []
        
        if len(items) == 1:
            return items
        
        # First, remove exact duplicates (case-insensitive)
        seen_exact = set()
        exact_unique_items = []
        for item in items:
            normalized_title = item.title.lower().strip()
            if normalized_title not in seen_exact:
                seen_exact.add(normalized_title)
                exact_unique_items.append(item)
        
        if len(exact_unique_items) == len(items):
            # No exact duplicates, check for near-duplicates with LLM
            if not self.use_ai:
                # If LLM not available, return items as-is
                logger.debug("LLM not available for duplicate detection, skipping near-duplicate check")
                return exact_unique_items
            
            try:
                near_duplicate_groups = await self._detect_near_duplicates(exact_unique_items)
                unique_items = self._keep_first_from_groups(exact_unique_items, near_duplicate_groups)
            except Exception as e:
                logger.error(f"Error detecting near-duplicates with LLM: {e}")
                # Fallback: return exact unique items
                unique_items = exact_unique_items
        else:
            # Had exact duplicates, now check near-duplicates on the unique set
            if self.use_ai:
                try:
                    near_duplicate_groups = await self._detect_near_duplicates(exact_unique_items)
                    unique_items = self._keep_first_from_groups(exact_unique_items, near_duplicate_groups)
                except Exception as e:
                    logger.error(f"Error detecting near-duplicates with LLM: {e}")
                    unique_items = exact_unique_items
            else:
                unique_items = exact_unique_items
        
        duplicates_removed = len(items) - len(unique_items)
        if duplicates_removed > 0:
            logger.info(
                f"Removed {duplicates_removed} duplicate/near-duplicate titles, "
                f"keeping {len(unique_items)}/{len(items)} unique items"
            )
        
        return unique_items
    
    async def _detect_near_duplicates(self, items: List[NewsItem]) -> List[List[int]]:
        """
        Use LLM to detect groups of near-duplicate titles.
        
        Args:
            items: List of NewsItem objects
            
        Returns:
            List of groups, where each group is a list of indices that are near-duplicates
        """
        # Build list of titles with indices
        titles_text = []
        for i, item in enumerate(items):
            titles_text.append(f"{i+1}. {item.title}")
        
        prompt = f"""You are a duplicate detection system. Analyze the following news article titles and identify groups of titles that are essentially the same or very similar (near-duplicates).

Two titles are near-duplicates if:
- They convey the same information with only minor wording differences
- They have the same core meaning but different phrasing
- They are the same story reported slightly differently
- They differ only in punctuation, capitalization, or minor words

Two titles are NOT duplicates if:
- They are about different events or topics
- They have significantly different information
- They are about the same company but different news

News titles to analyze:
{chr(10).join(titles_text)}

Return a JSON array of arrays, where each inner array contains the numbers (1-based indices) of titles that are near-duplicates.
Example: [[1, 3], [5, 7, 9]] means titles 1 and 3 are duplicates, and titles 5, 7, and 9 are duplicates.

If there are no duplicates, return an empty array: []

Return ONLY the JSON array, no other text."""

        try:
            if self.use_new_sdk:
                response_text = await self._call_new_sdk(prompt)
            else:
                response_text = await self._call_old_sdk(prompt)
            
            if not response_text:
                return []
            
            content = response_text.strip()
            
            # Check if content is empty after stripping
            if not content:
                logger.warning("Gemini returned empty content after stripping for duplicate detection")
                return []
            
            # Clean up markdown code blocks if present
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Check again after cleaning markdown
            if not content:
                logger.warning("Gemini returned empty content after markdown cleanup for duplicate detection")
                return []
            
            # Parse JSON response
            groups = json.loads(content)
            
            # Validate: convert 1-based indices to 0-based and validate ranges
            valid_groups = []
            for group in groups:
                if not isinstance(group, list):
                    continue
                # Convert 1-based to 0-based indices
                indices = [idx - 1 for idx in group if isinstance(idx, int) and 1 <= idx <= len(items)]
                if len(indices) > 1:  # Only keep groups with at least 2 items
                    valid_groups.append(indices)
            
            return valid_groups
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse duplicate detection JSON response: {e}")
            content_preview = content[:500] if 'content' in locals() and content else 'Empty or None'
            logger.debug(f"Response content (first 500 chars): {content_preview}")
            logger.debug(f"Response content length: {len(content) if 'content' in locals() and content else 0}")
            return []
        
        except Exception as e:
            logger.error(f"Error calling Gemini for duplicate detection: {e}")
            return []
    
    def _keep_first_from_groups(self, items: List[NewsItem], groups: List[List[int]]) -> List[NewsItem]:
        """
        Keep only the first item from each duplicate group.
        
        Args:
            items: List of NewsItem objects
            groups: List of groups, where each group is a list of indices that are duplicates
            
        Returns:
            List of NewsItem objects with duplicates removed
        """
        if not groups:
            return items
        
        # Collect all indices to remove (all except first in each group)
        indices_to_remove = set()
        for group in groups:
            if len(group) > 1:
                # Keep first, remove rest
                indices_to_remove.update(group[1:])
        
        # Filter out items at indices to remove
        unique_items = [item for i, item in enumerate(items) if i not in indices_to_remove]
        
        return unique_items
    
    async def filter(
        self,
        items: List[NewsItem],
        ticker: str
    ) -> List[NewsItem]:
        """
        Filter news items using Gemini to check relevance to ticker.
        
        Args:
            items: List of NewsItem objects to filter
            ticker: Stock ticker symbol to check relevance against
            
        Returns:
            Filtered list of NewsItem objects relevant to the ticker
        """
        if not items:
            return []
        
        # Remove duplicate titles first (before relevance checking) only if more than 500 items
        if len(items) > 500:
            items = await self._remove_duplicate_titles(items)
        
        if not items:
            return []
        
        if not self.use_ai:
            if self.fallback_filter:
                logger.info(f"Using keyword fallback for {len(items)} items")
                return await self.fallback_filter.filter(items, ticker)
            else:
                logger.warning("Gemini unavailable and no fallback, returning all items")
                return items
        
        ticker_normalized = self._normalize_ticker(ticker)
        filtered = []
        
        # Process in batches
        for i in range(0, len(items), self.batch_size):
            batch = items[i:i + self.batch_size]
            
            try:
                # Check relevance for this batch
                relevance_results = await self._check_relevance_batch(batch, ticker_normalized)
                
                # Filter based on results
                for item, is_relevant in zip(batch, relevance_results):
                    if is_relevant:
                        filtered.append(item)
                    else:
                        logger.debug(f"Gemini filtered out: {item.title[:50]}")
            
            except Exception as e:
                logger.error(f"Error in Gemini batch processing: {e}")
                # Fallback to keyword filter for this batch
                if self.fallback_filter:
                    batch_filtered = await self.fallback_filter.filter(batch, ticker)
                    filtered.extend(batch_filtered)
                else:
                    # If no fallback, include all items in batch
                    filtered.extend(batch)
        
        logger.info(
            f"Gemini filter: {len(filtered)}/{len(items)} items relevant to {ticker}"
        )
        return filtered
    
    async def _check_relevance_batch(
        self,
        items: List[NewsItem],
        ticker: str
    ) -> List[bool]:
        """
        Check relevance for a batch of news items using Gemini.
        
        Args:
            items: List of NewsItem objects
            ticker: Ticker symbol to check relevance against
            
        Returns:
            List of booleans indicating relevance for each item
        """
        # Build prompt with all items in batch
        items_text = []
        for i, item in enumerate(items):
            title = item.title
            summary = item.summary or "No summary available"
            items_text.append(f"{i+1}. Title: {title}\n   Summary: {summary}")
        
        prompt = f"""You are a financial news relevance checker. Determine if each news article is relevant to stock ticker {ticker}.

A news article is relevant if:
- It mentions the ticker symbol {ticker} or the company name
- It discusses the company's business, products, financial results, or operations
- It covers events that directly impact the company (earnings, mergers, lawsuits, etc.)
- It discusses market trends or sectors that the company operates in

A news article is NOT relevant if:
- It only mentions {ticker} in passing or in a list
- It's about a different company with a similar name
- It's general market news with no specific connection to {ticker}
- It's about unrelated topics

News articles to check:
{chr(10).join(items_text)}

Return a JSON array of booleans, one for each article (true if relevant to {ticker}, false otherwise).
Example: [true, false, true, false, ...]

Return ONLY the JSON array, no other text."""

        try:
            if self.use_new_sdk:
                response = await self._call_new_sdk(prompt)
            else:
                response = await self._call_old_sdk(prompt)
            
            if not response:
                # Fallback
                if self.fallback_filter:
                    fallback_results = await self.fallback_filter.filter(items, ticker)
                    return [item in fallback_results for item in items]
                return [True] * len(items)
            
            content = response.strip()
            
            # Check if content is empty after stripping
            if not content:
                logger.warning("Gemini returned empty content after stripping for relevance check")
                if self.fallback_filter:
                    fallback_results = await self.fallback_filter.filter(items, ticker)
                    return [item in fallback_results for item in items]
                return [True] * len(items)
            
            # Clean up markdown code blocks if present
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Check again after cleaning markdown
            if not content:
                logger.warning("Gemini returned empty content after markdown cleanup for relevance check")
                if self.fallback_filter:
                    fallback_results = await self.fallback_filter.filter(items, ticker)
                    return [item in fallback_results for item in items]
                return [True] * len(items)
            
            # Parse JSON response
            results = json.loads(content)
            
            # Validate length
            if len(results) != len(items):
                logger.warning(
                    f"Gemini returned {len(results)} results for {len(items)} items, "
                    "using keyword fallback for this batch"
                )
                if self.fallback_filter:
                    fallback_results = await self.fallback_filter.filter(items, ticker)
                    return [item in fallback_results for item in items]
                else:
                    # Default to all relevant if we can't determine
                    return [True] * len(items)
            
            return results
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini JSON response: {e}")
            content_preview = content[:500] if 'content' in locals() and content else 'Empty or None'
            logger.debug(f"Response content (first 500 chars): {content_preview}")
            logger.debug(f"Response content length: {len(content) if 'content' in locals() and content else 0}")
            # Fallback
            if self.fallback_filter:
                fallback_results = await self.fallback_filter.filter(items, ticker)
                return [item in fallback_results for item in items]
            return [True] * len(items)
        
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}")
            # Fallback
            if self.fallback_filter:
                fallback_results = await self.fallback_filter.filter(items, ticker)
                return [item in fallback_results for item in items]
            return [True] * len(items)
    
    async def _call_new_sdk(self, prompt: str) -> Optional[str]:
        """Call Gemini using the new SDK (google-genai)."""
        try:
            import asyncio
            # New SDK: google.genai
            model = genai.GenerativeModel(self.model)
            # Check if async method exists, otherwise use executor
            if hasattr(model, 'generate_content_async'):
                response = await model.generate_content_async(prompt)
            else:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: model.generate_content(prompt)
                )
            return response.text if response and response.text else None
        except Exception as e:
            logger.error(f"Error calling Gemini (new SDK): {e}")
            return None
    
    async def _call_old_sdk(self, prompt: str) -> Optional[str]:
        """Call Gemini using the old SDK (google-generativeai)."""
        try:
            import asyncio
            # Old SDK: google.generativeai (synchronous)
            model = genai.GenerativeModel(self.model)
            # Old SDK is synchronous, run in executor
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: model.generate_content(prompt)
            )
            return response.text if response and response.text else None
        except Exception as e:
            logger.error(f"Error calling Gemini (old SDK): {e}")
            return None
