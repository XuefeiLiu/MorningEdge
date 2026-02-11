"""
News Collection and Storage Module

Handles collecting news articles and storing them with embeddings.
Uses Alpha Vantage, Massive, and Gemini APIs (same logic as news_articles_daily.py).
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict

from supabase import Client

from backend.models import NewsItem
from backend.storage.news_articles_save import convert_to_db_format, save_articles, _string_id_to_bigint
from backend.storage.news_articles_query import get_articles
from backend.storage.embedding_utils import get_embeddings
from backend.services.collectors.alpha_vantage import AlphaVantageCollector
from backend.services.collectors.massive import MassiveCollector
from backend.services.collectors.gemini import GeminiCollector
from backend.services.news_filters import OpenAIFilter
from backend.config import ALPHA_VANTAGE_API_KEY, MASSIVE_API_KEY, is_gemini_generated

logger = logging.getLogger(__name__)


async def collect_todays_news(
    ticker: str,
    supabase: Client = None,
    *,
    include_gemini: bool = True,
    include_alpha_vantage: bool = True,
    include_massive: bool = True,
) -> List[NewsItem]:
    """
    Collect news for a ticker from the last 24 hours (now minus 24 hours to now).
    Can restrict to specific sources (Gemini only used for pipeline storyline phase).

    Args:
        ticker: Stock ticker symbol
        supabase: Optional Supabase client for querying existing articles
        include_gemini: If True, fetch from Gemini (default True)
        include_alpha_vantage: If True, fetch from Alpha Vantage (default True)
        include_massive: If True, fetch from Massive (default True)

    Returns:
        List of NewsItem objects (filtered for relevance and duplicates)
    """
    logger.info(f"Collecting news for {ticker} from last 24 hours (gemini={include_gemini}, av={include_alpha_vantage}, massive={include_massive})...")

    # Time range: last 24 hours (now minus 24 hours to now), in UTC.
    # Massive API uses UTC for published_utc.gte/lte; Alpha Vantage uses ET for time_from/time_to
    # (AlphaVantageCollector converts this window to ET internally).
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=24)
    end_time = now

    logger.info(f"Time range for {ticker}: {start_time.isoformat()} to {end_time.isoformat()}")

    all_news_items = []

    try:
        async def _fetch_gemini() -> List[NewsItem]:
            collector = GeminiCollector()
            if not collector.is_available:
                logger.debug(f"Gemini collector unavailable for {ticker}")
                return []
            news = await collector.collect_news([ticker], start_time, end_time)
            logger.debug(f"Gemini returned {len(news) if news else 0} items for {ticker}")
            return news or []

        async def _fetch_alpha_vantage() -> List[NewsItem]:
            collector = AlphaVantageCollector()
            if not collector.is_available:
                logger.debug(f"Alpha Vantage collector unavailable for {ticker}")
                return []
            news = await collector.collect_news([ticker], start_time, end_time)
            logger.debug(f"Alpha Vantage returned {len(news) if news else 0} items for {ticker}")
            return news or []

        async def _fetch_massive() -> List[NewsItem]:
            collector = MassiveCollector(api_key=MASSIVE_API_KEY)
            if not collector.is_available:
                logger.debug(f"Massive collector unavailable for {ticker}")
                return []
            news = await collector.collect_news([ticker], start_time, end_time)
            logger.debug(f"Massive returned {len(news) if news else 0} items for {ticker}")
            return news or []

        tasks = []
        if include_gemini:
            tasks.append(_fetch_gemini())
        if include_alpha_vantage:
            tasks.append(_fetch_alpha_vantage())
        if include_massive:
            tasks.append(_fetch_massive())
        if not tasks:
            logger.warning("No sources enabled for collect_todays_news")
            return []
        results = await asyncio.gather(*tasks)
        for news_list in results:
            all_news_items.extend(news_list)

        if not all_news_items:
            logger.info(f"No news items collected for {ticker}")
            return []
        
        # Query existing articles from the same time range to check for duplicates
        existing_articles = []
        if supabase:
            try:
                existing_articles = get_articles(
                    supabase,
                    ticker=ticker,
                    start_date=start_time,
                    end_date=end_time
                )
                logger.info(f"Found {len(existing_articles)} existing articles in time range for {ticker}")
            except Exception as e:
                logger.warning(f"Could not query existing articles for duplicate check: {e}")
        
        # Filter news items for relevance to the ticker (same as news_articles_daily.py)
        logger.info(f"Filtering {len(all_news_items)} news items for {ticker}...")
        news_filter = OpenAIFilter(use_fallback=True)
        filtered_news = await news_filter.filter(all_news_items, ticker, existing_articles=existing_articles)
        logger.info(f"Filtered to {len(filtered_news)} relevant items for {ticker}")
        
        return filtered_news
        
    except Exception as e:
        logger.error(f"Error collecting news for {ticker}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


async def store_news_with_embeddings(
    supabase: Client,
    ticker: str,
    news_items: List[NewsItem]
) -> List[Dict]:
    """
    Store news articles with embeddings in the database.
    Gemini-generated articles are not saved to news_articles.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        news_items: List of NewsItem objects
        
    Returns:
        List of stored article dicts with database IDs
    """
    if not news_items:
        return []
    news_items = [item for item in news_items if not is_gemini_generated(getattr(item, "collector", None), getattr(item, "source", None))]
    if not news_items:
        logger.info(f"Skipping save for {ticker}: all items are Gemini-generated (not saved to news_articles)")
        return []
    logger.info(f"Storing {len(news_items)} news items with embeddings for {ticker}...")
    
    # Get embeddings for summaries (fallback to title if summary is None)
    summary_texts = [item.summary or item.title for item in news_items]
    embeddings = await get_embeddings(summary_texts)
    
    # Add embeddings to NewsItem objects
    if embeddings is not None and len(embeddings) == len(news_items):
        for i, item in enumerate(news_items):
            item.embedding = embeddings[i].tolist()
        logger.info(f"Added embeddings to {len(news_items)} items")
    else:
        logger.warning(f"Failed to get embeddings for {ticker}, continuing without embeddings")
    
    # Convert to DB format and save
    db_items = [convert_to_db_format(item, ticker) for item in news_items]
    
    # Save articles (use combined source name)
    saved_count = save_articles(
        supabase,
        ticker,
        db_items,
        source="Pipeline (Alpha Vantage + Massive + Gemini)",
        start_date=None,
        end_date=None
    )
    
    logger.info(f"Stored {saved_count} new articles for {ticker}")
    
    # Batch fetch stored articles (1 query instead of M)
    db_ids = [_string_id_to_bigint(item.id) for item in news_items]
    id_to_row: Dict[int, Dict] = {}
    try:
        result = supabase.table("news_articles").select("*").in_("id", db_ids).execute()
        if result.data:
            for row in result.data:
                id_to_row[int(row["id"])] = row
    except Exception as e:
        logger.warning(f"Could not batch retrieve stored articles: {e}")
    stored_articles = []
    for item in news_items:
        db_id = _string_id_to_bigint(item.id)
        row = id_to_row.get(db_id)
        if row is not None:
            stored_articles.append(row)
    return stored_articles
