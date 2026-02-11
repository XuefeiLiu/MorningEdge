"""
Query operations for stocks table.
"""
import logging
from typing import List, Dict, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_stock(supabase: Client, ticker: str) -> Optional[Dict]:
    """
    Get single stock by ticker.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol (case-insensitive)
        
    Returns:
        Stock dict with keys: ticker, name, exchange, or None if not found
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        result = supabase.table("stocks").select("*").eq("ticker", ticker.upper()).limit(1).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error querying stock {ticker}: {e}")
        return None


def get_stocks(supabase: Client, tickers: Optional[List[str]] = None) -> List[Dict]:
    """
    Get stocks by ticker list, or all if None.
    
    Args:
        supabase: Supabase client instance
        tickers: Optional list of ticker symbols. If None, returns all stocks.
        
    Returns:
        List of stock dicts with keys: ticker, name, exchange
    """
    if not supabase:
        supabase = get_supabase_client()
    
    try:
        query = supabase.table("stocks").select("*")
        
        if tickers:
            # Convert to uppercase for consistency
            tickers_upper = [t.upper() for t in tickers]
            query = query.in_("ticker", tickers_upper)
        
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error querying stocks: {e}")
        return []


def get_all_stocks(supabase: Client) -> List[Dict]:
    """
    Get all stocks from database.
    
    Args:
        supabase: Supabase client instance
        
    Returns:
        List of stock dicts with keys: ticker, name, exchange
    """
    return get_stocks(supabase, tickers=None)
