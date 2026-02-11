"""
LLM-based news relevance filter.
Uses OpenAI API directly to determine if news items are relevant to a ticker.
Requires OPENAI_API_KEY to be configured.
"""
import logging
import json
import asyncio
from typing import List, Optional, Dict
from collections import defaultdict
from datetime import datetime

import numpy as np

from backend.models import NewsItem
from backend.config import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    OPENAI_FILTER_BATCH_SIZE,
    OPENAI_FILTER_MAX_CONCURRENT_BATCHES,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from backend.services.embedding_service import get_embedding_service
from .base import NewsFilter
from .keyword_filter import KeywordRelevanceFilter

logger = logging.getLogger(__name__)

# Try to import OpenAI SDK
try:
    from openai import AsyncOpenAI
    OPENAI_SDK_AVAILABLE = True
except ImportError:
    OPENAI_SDK_AVAILABLE = False
    logger.error("OpenAI SDK not installed. LLMFilter requires it.")


class LLMFilter(NewsFilter):
    """
    Filters news items using OpenAI API to check relevance to a ticker.
    Requires OPENAI_API_KEY to be configured. Fails if not configured.
    """
    
    DEFAULT_BATCH_SIZE = 10
    DEFAULT_MAX_CONCURRENT_BATCHES = 10
    
    def __init__(
        self,
        batch_size: int = None,
        max_concurrent_batches: int = None,
        use_fallback: bool = True
    ):
        """
        Initialize LLM filter.
        
        Args:
            batch_size: Number of items to process per API call (default: from config or 10)
            max_concurrent_batches: Maximum number of batches to process concurrently (default: from config or 10)
            use_fallback: Whether to fall back to keyword filter if LLM fails (default: True)
        
        Raises:
            ValueError: If OPENAI_API_KEY is not configured
        """
        super().__init__("llm")
        
        # Require OpenAI API key
        if not OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is required for LLMFilter. Configure it and retry."
            )
        
        if not OPENAI_SDK_AVAILABLE:
            raise ValueError(
                "OpenAI SDK is required for LLMFilter. Install it with: pip install openai"
            )
        
        self.batch_size = batch_size or OPENAI_FILTER_BATCH_SIZE or self.DEFAULT_BATCH_SIZE
        self.max_concurrent_batches = max_concurrent_batches or OPENAI_FILTER_MAX_CONCURRENT_BATCHES or self.DEFAULT_MAX_CONCURRENT_BATCHES
        self.use_fallback = use_fallback
        self.llm_model = OPENAI_MODEL
        
        # Initialize OpenAI client (defaults to api.openai.com)
        try:
            self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
            self.use_ai = True
            logger.info(
                f"LLMFilter initialized with OpenAI model: {self.llm_model} "
                f"(for relevance checking; embeddings via centralized embedding service)"
            )
        except Exception as e:
            raise ValueError(f"Failed to initialize OpenAI client: {e}")
        
        # Initialize fallback filter
        if self.use_fallback:
            self.fallback_filter = KeywordRelevanceFilter()
        else:
            self.fallback_filter = None
        
        # Initialize embedding service
        self.embedding_service = get_embedding_service()
    
    async def _remove_duplicate_titles(
        self, 
        items: List[NewsItem],
        existing_articles: Optional[List[Dict]] = None
    ) -> List[NewsItem]:
        """
        Remove duplicate and near-duplicate news items based on title.
        Groups items by published date first, then removes duplicates within each date group.
        Also checks against existing articles from the database and removes new items that are duplicates.
        Uses embedding-based similarity to detect near-duplicates.
        Keeps the first occurrence of each unique title within each date group.
        
        Optimized to get all embeddings in one API call instead of per date group.
        
        Args:
            items: List of NewsItem objects
            existing_articles: Optional list of existing article dicts from database (with 'title' and 'published_at' keys)
            
        Returns:
            List of NewsItem objects with duplicate titles removed (including duplicates of existing articles)
        """
        if not items:
            return []
        
        # Convert existing articles to a simple format for duplicate checking
        existing_titles_by_date = defaultdict(list)  # Dict[date_str, List[title]]
        if existing_articles:
            for article in existing_articles:
                title = article.get("title", "")
                published_at_str = article.get("published_at", "")
                if title and published_at_str:
                    try:
                        # Parse published_at (could be ISO string or datetime)
                        if isinstance(published_at_str, str):
                            from datetime import datetime
                            published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                        else:
                            published_at = published_at_str
                        date_key = published_at.date().isoformat() if hasattr(published_at, 'date') else "unknown"
                        existing_titles_by_date[date_key].append(title.lower().strip())
                    except Exception as e:
                        logger.debug(f"Error parsing existing article date: {e}")
                        # Fallback: add to "unknown" date
                        existing_titles_by_date["unknown"].append(title.lower().strip())
        
        # Check for exact duplicates against existing articles first (fast check)
        items_to_check = []
        exact_duplicates_of_existing = 0
        for item in items:
            item_date_key = item.published_at.date().isoformat() if item.published_at else "unknown"
            normalized_title = item.title.lower().strip()
            
            # Check if this title already exists in the database for this date
            is_duplicate = False
            if item_date_key in existing_titles_by_date:
                if normalized_title in existing_titles_by_date[item_date_key]:
                    is_duplicate = True
                    exact_duplicates_of_existing += 1
                    logger.debug(f"Exact duplicate of existing article: {item.title[:50]}")
            # Also check "unknown" date group
            if not is_duplicate and "unknown" in existing_titles_by_date:
                if normalized_title in existing_titles_by_date["unknown"]:
                    is_duplicate = True
                    exact_duplicates_of_existing += 1
                    logger.debug(f"Exact duplicate of existing article (unknown date): {item.title[:50]}")
            
            if not is_duplicate:
                items_to_check.append(item)
        
        if exact_duplicates_of_existing > 0:
            logger.info(
                f"Removed {exact_duplicates_of_existing} new articles that are exact duplicates of existing articles"
            )
        
        if not items_to_check:
            return []
        
        if len(items_to_check) == 1:
            return items_to_check
        
        # Get embeddings for existing articles (if any) to check for near-duplicates
        existing_embeddings = None
        existing_titles_list = []
        if existing_articles:
            existing_titles_list = [article.get("title", "") for article in existing_articles if article.get("title")]
            if existing_titles_list:
                existing_embeddings = await self.embedding_service.get_embeddings(existing_titles_list)
                if existing_embeddings is not None:
                    logger.debug(f"Got embeddings for {len(existing_titles_list)} existing articles")
                else:
                    logger.warning("Failed to get embeddings for existing articles, skipping near-duplicate check against them")
        
        # Get all embeddings upfront (one API call instead of per date group)
        all_titles = [item.title for item in items_to_check]
        all_embeddings = await self.embedding_service.get_embeddings(all_titles)
        
        # Check for near-duplicates against existing articles if we have embeddings
        items_after_existing_check = items_to_check
        near_duplicates_of_existing = 0
        if existing_embeddings is not None and all_embeddings is not None:
            # Calculate similarity matrix: new_articles x existing_articles
            similarity_matrix = self.embedding_service.compute_similarity_matrix(
                all_embeddings, existing_embeddings
            )
            
            # Find new articles that are near-duplicates of existing ones
            items_after_existing_check = []
            for i, item in enumerate(items_to_check):
                # Check similarity against all existing articles
                max_similarity = np.max(similarity_matrix[i])
                if max_similarity >= DUPLICATE_SIMILARITY_THRESHOLD:
                    near_duplicates_of_existing += 1
                    logger.debug(
                        f"Near-duplicate of existing article (similarity: {max_similarity:.3f}): {item.title[:50]}"
                    )
                else:
                    items_after_existing_check.append(item)
            
            if near_duplicates_of_existing > 0:
                logger.info(
                    f"Removed {near_duplicates_of_existing} new articles that are near-duplicates of existing articles "
                    f"(similarity >= {DUPLICATE_SIMILARITY_THRESHOLD})"
                )
        else:
            items_after_existing_check = items_to_check
        
        if not items_after_existing_check:
            return []
        
        if len(items_after_existing_check) == 1:
            return items_after_existing_check
        
        # Recompute embeddings for remaining items if we filtered some out
        if len(items_after_existing_check) < len(items_to_check):
            all_titles = [item.title for item in items_after_existing_check]
            all_embeddings = await self.embedding_service.get_embeddings(all_titles)
        
        # Group items by published date (date only, not time) for remaining items
        # Store both items and their original indices
        items_by_date: Dict[str, List[tuple]] = defaultdict(list)  # List of (item, original_index) tuples
        for idx, item in enumerate(items_after_existing_check):
            # Extract date part from published_at
            date_key = item.published_at.date().isoformat() if item.published_at else "unknown"
            items_by_date[date_key].append((item, idx))
        
        if all_embeddings is None:
            logger.warning("Failed to get embeddings, skipping near-duplicate detection, only removing exact duplicates")
            # Fallback: only remove exact duplicates
            all_unique_items = []
            for date_key, date_items_with_indices in items_by_date.items():
                seen_exact = set()
                for item, _ in date_items_with_indices:
                    normalized_title = item.title.lower().strip()
                    if normalized_title not in seen_exact:
                        seen_exact.add(normalized_title)
                        all_unique_items.append(item)
            return all_unique_items
        
        if len(all_embeddings) != len(items_after_existing_check):
            logger.error(f"Embedding count mismatch: {len(all_embeddings)} embeddings for {len(items_after_existing_check)} items")
            # Fallback: only remove exact duplicates
            all_unique_items = []
            for date_key, date_items_with_indices in items_by_date.items():
                seen_exact = set()
                for item, _ in date_items_with_indices:
                    normalized_title = item.title.lower().strip()
                    if normalized_title not in seen_exact:
                        seen_exact.add(normalized_title)
                        all_unique_items.append(item)
            return all_unique_items
        
        # Process duplicates within each date group using pre-computed embeddings
        all_unique_items = []
        
        for date_key, date_items_with_indices in items_by_date.items():
            if len(date_items_with_indices) == 1:
                # Single item for this date, no duplicates possible
                all_unique_items.append(date_items_with_indices[0][0])
                continue
            
            # Extract items and indices
            date_items = [item for item, _ in date_items_with_indices]
            date_indices = [idx for _, idx in date_items_with_indices]
            
            # Remove exact duplicates (case-insensitive) within this date group
            seen_exact = set()
            exact_unique_items = []
            exact_unique_indices = []  # Track original indices for embedding lookup
            for item, orig_idx in date_items_with_indices:
                normalized_title = item.title.lower().strip()
                if normalized_title not in seen_exact:
                    seen_exact.add(normalized_title)
                    exact_unique_items.append(item)
                    exact_unique_indices.append(orig_idx)
            
            exact_duplicates_removed = len(date_items) - len(exact_unique_items)
            if exact_duplicates_removed > 0:
                logger.debug(
                    f"Date {date_key}: Removed {exact_duplicates_removed} exact duplicates, "
                    f"keeping {len(exact_unique_items)}/{len(date_items)} items"
                )
            
            # Get embeddings for this date group's unique items (slice from pre-computed embeddings)
            date_embeddings = all_embeddings[exact_unique_indices]
            
            # Check for near-duplicates using embeddings
            try:
                near_duplicate_groups = await self._detect_near_duplicates(exact_unique_items, date_embeddings)
                unique_items = self._keep_first_from_groups(exact_unique_items, near_duplicate_groups)
                near_duplicates_removed = len(exact_unique_items) - len(unique_items)
                if near_duplicates_removed > 0:
                    logger.debug(
                        f"Date {date_key}: Removed {near_duplicates_removed} near-duplicates, "
                        f"keeping {len(unique_items)}/{len(exact_unique_items)} items"
                    )
                all_unique_items.extend(unique_items)
            except Exception as e:
                logger.error(f"Error detecting near-duplicates for date {date_key}: {e}")
                # Fallback: return exact unique items for this date
                all_unique_items.extend(exact_unique_items)
        
        # Also count near-duplicates removed (including duplicates of existing articles)
        total_removed = len(items) - len(all_unique_items)
        total_existing_duplicates = exact_duplicates_of_existing + near_duplicates_of_existing
        if total_removed > 0:
            logger.info(
                f"Removed {total_removed} duplicate/near-duplicate titles "
                f"(including {total_existing_duplicates} duplicates of existing articles: "
                f"{exact_duplicates_of_existing} exact, {near_duplicates_of_existing} near-duplicates), "
                f"keeping {len(all_unique_items)}/{len(items)} unique items"
            )
        
        return all_unique_items
    
    def _extract_json_array(self, content: str) -> Optional[str]:
        """
        Extract JSON array from text that might contain extra content.
        Uses balanced bracket matching to find the outermost array.
        
        Args:
            content: Text that may contain a JSON array
            
        Returns:
            Extracted JSON string or None if not found
        """
        # Find the first opening bracket
        start_idx = content.find('[')
        if start_idx == -1:
            return None
        
        # Find matching closing bracket by counting brackets
        # This handles nested arrays correctly
        bracket_count = 0
        in_string = False
        escape_next = False
        
        for i in range(start_idx, len(content)):
            char = content[i]
            
            # Handle string escaping
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            # Track if we're inside a string (brackets inside strings don't count)
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            
            if not in_string:
                if char == '[':
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        # Found matching closing bracket
                        return content[start_idx:i+1]
        
        # No matching closing bracket found
        return None
    
    async def _detect_near_duplicates(
        self, 
        items: List[NewsItem], 
        embeddings: Optional[np.ndarray] = None
    ) -> List[List[int]]:
        """
        Use embedding-based similarity to detect groups of near-duplicate titles.
        
        Args:
            items: List of NewsItem objects
            embeddings: Optional pre-computed embeddings array (n_items, embedding_dim).
                       If None, embeddings will be fetched from the API.
            
        Returns:
            List of groups, where each group is a list of indices that are near-duplicates
        """
        if not items:
            return []
        
        if len(items) == 1:
            return []
        
        # Get embeddings if not provided
        if embeddings is None:
            # Get titles
            titles = [item.title for item in items]
            
            # Get embeddings for all titles
            embeddings = await self.embedding_service.get_embeddings(titles)
            if embeddings is None:
                logger.warning("Failed to get embeddings, skipping duplicate detection")
                return []
        
        if len(embeddings) != len(items):
            logger.error(f"Embedding count mismatch: {len(embeddings)} embeddings for {len(items)} items")
            return []
        
        # Calculate pairwise cosine similarities using matrix multiplication
        # This is much faster than calculating pairwise similarities one by one
        normalized_embeddings = self.embedding_service.normalize_embeddings(embeddings)
        similarity_matrix = np.dot(normalized_embeddings, normalized_embeddings.T)
        
        # Find duplicate groups
        similarity_threshold = DUPLICATE_SIMILARITY_THRESHOLD
        groups = []
        processed = set()
        
        for i in range(len(items)):
            if i in processed:
                continue
            
            # Find all items similar to item i (using pre-computed similarity matrix)
            group = [i]
            for j in range(i + 1, len(items)):
                if j in processed:
                    continue
                
                similarity = similarity_matrix[i, j]
                if similarity >= similarity_threshold:
                    group.append(j)
                    processed.add(j)
            
            # Only add groups with at least 2 items
            if len(group) > 1:
                groups.append(group)
                processed.add(i)
        
        if groups:
            total_duplicates = sum(len(g) - 1 for g in groups)  # -1 because we keep one from each group
            logger.debug(
                f"Found {len(groups)} duplicate groups ({total_duplicates} duplicates) "
                f"using embedding similarity (threshold: {similarity_threshold})"
            )
        
        return groups
    
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
        ticker: str,
        existing_articles: Optional[List[Dict]] = None
    ) -> List[NewsItem]:
        """
        Filter news items using OpenAI LLM to check relevance to ticker.
        
        Args:
            items: List of NewsItem objects to filter
            ticker: Stock ticker symbol to check relevance against
            existing_articles: Optional list of existing article dicts from database to check for duplicates
            
        Returns:
            Filtered list of NewsItem objects relevant to the ticker
        """
        if not items:
            return []
        
        # Step 1: Check relevance first (filter to only relevant items)
        if not self.client:
            if self.fallback_filter:
                logger.info(f"Using keyword fallback for {len(items)} items")
                filtered = await self.fallback_filter.filter(items, ticker)
            else:
                raise ValueError("LLM client not available and no fallback configured")
        else:
            ticker_normalized = self._normalize_ticker(ticker)
            filtered = []
            
            # Process batches in parallel with concurrency control
            semaphore = asyncio.Semaphore(self.max_concurrent_batches)
            
            async def process_batch_with_semaphore(batch: List[NewsItem], batch_idx: int) -> List[NewsItem]:
                """Process a single batch with semaphore control."""
                async with semaphore:
                    try:
                        # Check relevance for this batch
                        relevance_results = await self._check_relevance_batch(batch, ticker_normalized)
                        
                        # Filter based on results
                        batch_filtered = []
                        for item, is_relevant in zip(batch, relevance_results):
                            if is_relevant:
                                batch_filtered.append(item)
                            else:
                                logger.debug(f"LLM filtered out: {item.title[:50]}")
                        
                        return batch_filtered
                    except Exception as e:
                        logger.error(f"Error in LLM batch {batch_idx} processing: {e}")
                        # Fallback to keyword filter for this batch
                        if self.fallback_filter:
                            batch_filtered = await self.fallback_filter.filter(batch, ticker)
                            return batch_filtered
                        else:
                            # If no fallback, include all items in batch
                            return batch
            
            # Create tasks for all batches
            tasks = []
            for i in range(0, len(items), self.batch_size):
                batch = items[i:i + self.batch_size]
                batch_idx = i // self.batch_size
                tasks.append(process_batch_with_semaphore(batch, batch_idx))
            
            # Process all batches in parallel
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Collect results from all batches
            for batch_result in batch_results:
                if isinstance(batch_result, Exception):
                    logger.error(f"Batch processing exception: {batch_result}")
                    # Skip this batch if it failed completely
                    continue
                filtered.extend(batch_result)
            
            logger.info(
                f"LLM filter: {len(filtered)}/{len(items)} items relevant to {ticker} "
                f"(processed {len(tasks)} batches with max {self.max_concurrent_batches} concurrent)"
            )
        
        if not filtered:
            return []
        
        # Step 2: Remove duplicate titles from relevant items (including duplicates of existing articles)
        # Only do duplicate removal if we have multiple items or existing articles to check
        if len(filtered) > 1 or (existing_articles and len(existing_articles) > 0):
            filtered = await self._remove_duplicate_titles(filtered, existing_articles=existing_articles)
        
        return filtered
    
    async def _check_relevance_batch(
        self,
        items: List[NewsItem],
        ticker: str
    ) -> List[bool]:
        """
        Check relevance for a batch of news items using OpenAI LLM.
        
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
            response = await self.client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a financial news relevance checker. Return only valid JSON arrays of booleans."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_completion_tokens=200
            )
            
            content = response.choices[0].message.content
            if content is None:
                logger.warning("LLM returned empty content for relevance check")
                if self.fallback_filter:
                    fallback_results = await self.fallback_filter.filter(items, ticker)
                    return [item in fallback_results for item in items]
                return [True] * len(items)
            
            content = content.strip()
            
            # Check if content is empty after stripping
            if not content:
                logger.warning("LLM returned empty content after stripping for relevance check")
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
                logger.warning("LLM returned empty content after markdown cleanup for relevance check")
                if self.fallback_filter:
                    fallback_results = await self.fallback_filter.filter(items, ticker)
                    return [item in fallback_results for item in items]
                return [True] * len(items)
            
            # Try to parse JSON directly
            results = None
            try:
                results = json.loads(content)
            except json.JSONDecodeError as e1:
                # If direct parse fails, try to extract JSON array from text
                logger.debug(f"Direct JSON parse failed for relevance check: {e1}, attempting to extract JSON array...")
                extracted_json = self._extract_json_array(content)
                if extracted_json:
                    logger.debug(f"Extracted JSON array for relevance check (length: {len(extracted_json)} chars)")
                    try:
                        results = json.loads(extracted_json)
                        logger.debug("Successfully parsed extracted JSON array for relevance check")
                    except json.JSONDecodeError as e2:
                        logger.error(f"Extracted JSON parse failed for relevance check: {e2}")
                        logger.debug(f"Extracted JSON content (first 500 chars): {extracted_json[:500]}")
                        raise  # Re-raise to be caught by outer exception handler
                else:
                    logger.error("Could not extract JSON array from relevance check response")
                    logger.debug(f"Full response content (first 1000 chars): {content[:1000]}")
                    raise  # Re-raise to be caught by outer exception handler
            
            # Validate that results is a list
            if not isinstance(results, list):
                logger.error(f"Expected JSON array, got {type(results)}: {results}")
                if self.fallback_filter:
                    fallback_results = await self.fallback_filter.filter(items, ticker)
                    return [item in fallback_results for item in items]
                return [True] * len(items)
            
            # Validate length
            if len(results) != len(items):
                logger.warning(
                    f"LLM returned {len(results)} results for {len(items)} items, "
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
            logger.error(f"Failed to parse LLM JSON response: {e}")
            content_preview = content[:1000] if 'content' in locals() and content else 'Empty or None'
            logger.debug(f"Response content (first 1000 chars): {content_preview}")
            logger.debug(f"Response content length: {len(content) if 'content' in locals() and content else 0}")
            # Log the exact error position if available
            if hasattr(e, 'pos'):
                logger.debug(f"JSON error at position {e.pos}")
                if 'content' in locals() and content and e.pos < len(content):
                    start = max(0, e.pos - 50)
                    end = min(len(content), e.pos + 50)
                    logger.debug(f"Context around error: ...{content[start:end]}...")
            # Fallback
            if self.fallback_filter:
                fallback_results = await self.fallback_filter.filter(items, ticker)
                return [item in fallback_results for item in items]
            return [True] * len(items)
        
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
            # Fallback
            if self.fallback_filter:
                fallback_results = await self.fallback_filter.filter(items, ticker)
                return [item in fallback_results for item in items]
            return [True] * len(items)
