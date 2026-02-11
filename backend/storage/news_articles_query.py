"""
Query operations for news_articles table.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_articles_by_ticker(supabase: Client, ticker: str, limit: Optional[int] = None) -> List[Dict]:
    """
    Get articles for a ticker.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        limit: Optional limit on number of results
        
    Returns:
        List of article dicts, ordered by published_at descending
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        query = supabase.table("news_articles").select("*").eq("ticker", ticker.upper()).order("published_at", desc=True)
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error querying articles for ticker {ticker}: {e}")
        return []


def get_articles_by_date(supabase: Client, ticker: str, day: datetime) -> List[Dict]:
    """
    Get articles for a ticker on a specific date.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        day: Date to query (datetime object, will use date part only)
        
    Returns:
        List of article dicts for that date
    """
    if not supabase:
        supabase = get_supabase_client()
    
    # Ensure timezone-aware
    if day.tzinfo is None:
        day = day.replace(tzinfo=timezone.utc)
    
    # Get start and end of day
    start_of_day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = day.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    try:
        result = supabase.table("news_articles").select("*").eq("ticker", ticker.upper()).gte("published_at", start_of_day.isoformat()).lte("published_at", end_of_day.isoformat()).order("published_at", desc=True).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error querying articles for ticker {ticker} on {day.date()}: {e}")
        return []


def get_articles(
    supabase: Client,
    ticker: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Get articles with flexible filtering.
    
    Args:
        supabase: Supabase client instance
        ticker: Optional stock ticker symbol
        start_date: Optional start date (inclusive)
        end_date: Optional end date (inclusive)
        limit: Optional limit on number of results
        
    Returns:
        List of article dicts, ordered by published_at descending
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        query = supabase.table("news_articles").select("*")
        
        if ticker:
            query = query.eq("ticker", ticker.upper())
        
        if start_date:
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            query = query.gte("published_at", start_date.isoformat())
        
        if end_date:
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            query = query.lte("published_at", end_date.isoformat())
        
        query = query.order("published_at", desc=True)
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error querying articles: {e}")
        return []


def get_articles_by_created_time(
    supabase: Client,
    start_time: datetime,
    end_time: datetime,
    ticker: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    Get articles by created_at (ingestion time) in the given time range.

    Args:
        supabase: Supabase client instance
        start_time: Start of window (inclusive)
        end_time: End of window (inclusive)
        ticker: Optional stock ticker symbol
        limit: Optional limit on number of results

    Returns:
        List of article dicts, ordered by created_at descending
    """
    if not supabase:
        supabase = get_supabase_client()

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    try:
        query = (
            supabase.table("news_articles")
            .select("*")
            .gte("created_at", start_time.isoformat())
            .lte("created_at", end_time.isoformat())
            .order("created_at", desc=True)
        )
        if ticker:
            query = query.eq("ticker", ticker.upper())
        if limit:
            query = query.limit(limit)
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error("Error querying articles by created_time: %s", e)
        return []


def get_articles_by_published_time(
    supabase: Client,
    start_time: datetime,
    end_time: datetime,
    ticker: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    Get articles by published_at in the given time range.

    Args:
        supabase: Supabase client instance
        start_time: Start of window (inclusive)
        end_time: End of window (inclusive)
        ticker: Optional stock ticker symbol
        limit: Optional limit on number of results

    Returns:
        List of article dicts, ordered by published_at descending
    """
    if not supabase:
        supabase = get_supabase_client()

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    try:
        query = (
            supabase.table("news_articles")
            .select("*")
            .gte("published_at", start_time.isoformat())
            .lte("published_at", end_time.isoformat())
            .order("published_at", desc=True)
        )
        if ticker:
            query = query.eq("ticker", ticker.upper())
        if limit:
            query = query.limit(limit)
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error("Error querying articles by published_time: %s", e)
        return []
