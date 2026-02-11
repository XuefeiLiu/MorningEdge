"""
Save operations for stocks table.
"""
import logging
from typing import List, Dict
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def save_stocks(supabase: Client, stocks_data: List[Dict[str, str]]) -> int:
    """
    Save or update stocks in the stocks table.
    
    Args:
        supabase: Supabase client instance
        stocks_data: List of dicts with keys: ticker, name, exchange
        
    Returns:
        Number of stocks saved/updated
    """
    if not supabase:
        supabase = get_supabase_client()
    
    inserted = 0
    for stock in stocks_data:
        ticker = stock.get("ticker", "").upper()
        name = stock.get("name", "")
        exchange = stock.get("exchange", "NASDAQ")
        
        if not ticker:
            logger.warning(f"Skipping stock with empty ticker: {stock}")
            continue
        
        try:
            # Upsert using Supabase (ON CONFLICT handled by Supabase)
            result = supabase.table("stocks").upsert(
                {
                    "ticker": ticker,
                    "name": name,
                    "exchange": exchange
                },
                on_conflict="ticker"
            ).execute()
            
            if result.data:
                inserted += 1
        except Exception as e:
            logger.error(f"Error upserting stock {ticker}: {e}")
            continue
    
    logger.info(f"Saved {inserted} stocks in database")
    return inserted
