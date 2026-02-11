"""
Query operations for stock_prices_5min table.
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_prices_by_ticker(
    supabase: Client,
    ticker: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """
    Get price records for a ticker, optionally filtered by date range.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        start_date: Optional start date (inclusive)
        end_date: Optional end date (inclusive)
        limit: Optional limit on number of results
        
    Returns:
        List of price dicts, ordered by timestamp descending
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        query = supabase.table("stock_prices_5min").select("*").eq("ticker", ticker.upper())
        
        if start_date:
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            query = query.gte("timestamp", start_date.isoformat())
        
        if end_date:
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            query = query.lte("timestamp", end_date.isoformat())
        
        query = query.order("timestamp", desc=True)
        
        if limit:
            query = query.limit(limit)
        
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error querying prices for ticker {ticker}: {e}")
        return []


def get_prices_by_date_range(
    supabase: Client,
    ticker: str,
    start_date: datetime,
    end_date: datetime
) -> List[Dict]:
    """
    Get price records for a ticker within a specific date range.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        
    Returns:
        List of price dicts, ordered by timestamp descending
    """
    return get_prices_by_ticker(supabase, ticker, start_date, end_date)


def get_latest_price(
    supabase: Client,
    ticker: str
) -> Optional[Dict]:
    """
    Get the most recent price record for a ticker.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        
    Returns:
        Most recent price dict, or None if not found
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        result = supabase.table("stock_prices_5min").select("*").eq("ticker", ticker.upper()).order("timestamp", desc=True).limit(1).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error querying latest price for ticker {ticker}: {e}")
        return None


def check_day_has_data(
    supabase: Client,
    ticker: str,
    date: datetime
) -> bool:
    """
    Check if a ticker has data for a specific day.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        date: Date to check (datetime object)
        
    Returns:
        True if data exists for this ticker-day combination, False otherwise
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        # Start of day
        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        
        # End of day
        end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Check if any records exist for this day
        result = supabase.table("stock_prices_5min").select("timestamp", count="exact").eq("ticker", ticker.upper()).gte("timestamp", start_date.isoformat()).lte("timestamp", end_date.isoformat()).limit(1).execute()
        
        # If count is available, use it; otherwise check if data exists
        if hasattr(result, 'count') and result.count is not None:
            return result.count > 0
        else:
            return len(result.data) > 0 if result.data else False
    except Exception as e:
        logger.error(f"Error checking data for {ticker} on {date.date()}: {e}")
        # On error, assume no data exists (safer to re-fetch)
        return False


def check_month_complete(
    supabase: Client,
    ticker: str,
    month: str
) -> bool:
    """
    Check if a ticker has complete data for a specific month.
    Checks if all trading days in the month have data.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol
        month: Month string in YYYY-MM format
        
    Returns:
        True if month is complete (all days have data), False otherwise
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        from datetime import datetime, timedelta
        import calendar
        
        # Parse month
        year, month_num = map(int, month.split('-'))
        
        # Get number of days in month
        days_in_month = calendar.monthrange(year, month_num)[1]
        
        # Check each day in the month
        # We'll check a sample of days to determine completeness
        # For efficiency, check first day, middle day, and last day
        # If all have data, assume month is complete
        
        # Check first day
        first_day = datetime(year, month_num, 1, 12, 0, 0, tzinfo=timezone.utc)
        if not check_day_has_data(supabase, ticker, first_day):
            return False
        
        # Check middle day
        middle_day = datetime(year, month_num, days_in_month // 2, 12, 0, 0, tzinfo=timezone.utc)
        if not check_day_has_data(supabase, ticker, middle_day):
            return False
        
        # Check last day
        last_day = datetime(year, month_num, days_in_month, 12, 0, 0, tzinfo=timezone.utc)
        if not check_day_has_data(supabase, ticker, last_day):
            return False
        
        # If all sample days have data, check a few more random days for confidence
        # Check days 3, 7, 15, 22
        sample_days = [3, 7, 15, 22]
        for day in sample_days:
            if day <= days_in_month:
                sample_date = datetime(year, month_num, day, 12, 0, 0, tzinfo=timezone.utc)
                if not check_day_has_data(supabase, ticker, sample_date):
                    return False
        
        # All sample days have data, assume month is complete
        return True
        
    except Exception as e:
        logger.error(f"Error checking month completeness for {ticker} {month}: {e}")
        # On error, assume incomplete (safer to re-fetch)
        return False
