"""
Query operations for macro_articles table.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_macro_articles(
    supabase: Client,
    collector: Optional[str] = None,
    ticker: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Get macro articles with flexible filtering.
    
    Args:
        supabase: Supabase client instance
        collector: Optional collector name (e.g., "alpha_vantage")
        ticker: Optional ticker symbol - filters by related_tickers JSONB array
        start_date: Optional start date (inclusive)
        end_date: Optional end date (inclusive)
        limit: Optional limit on number of results
        
    Returns:
        List of article dicts, ordered by published_at descending
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        query = supabase.table("macro_articles").select("*")
        
        if collector:
            query = query.eq("collector", collector)
        
        if ticker:
            # Filter by ticker in related_tickers JSONB array
            # Use PostgREST cs (contains) operator: related_tickers @> '["AAPL"]'::jsonb
            ticker_upper = ticker.strip().upper()
            # Supabase Python client uses filter with cs operator for JSONB contains
            query = query.filter("related_tickers", "cs", f'["{ticker_upper}"]')
        
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
        logger.error(f"Error querying macro articles: {e}")
        return []


def get_macro_articles_by_date(
    supabase: Client,
    day: datetime,
    collector: Optional[str] = None,
    ticker: Optional[str] = None
) -> List[Dict]:
    """
    Get macro articles for a specific date.
    
    Args:
        supabase: Supabase client instance
        day: Date to query (datetime object, will use date part only)
        collector: Optional collector name
        ticker: Optional ticker symbol - filters by related_tickers
        
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
    
    return get_macro_articles(
        supabase=supabase,
        collector=collector,
        ticker=ticker,
        start_date=start_of_day,
        end_date=end_of_day
    )


def get_all_macro_articles(
    supabase: Client,
    collector: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Get all macro articles (no date filtering).
    
    Args:
        supabase: Supabase client instance
        collector: Optional collector name
        limit: Optional limit on number of results
        
    Returns:
        List of article dicts, ordered by published_at descending
    """
    return get_macro_articles(
        supabase=supabase,
        collector=collector,
        limit=limit
    )
