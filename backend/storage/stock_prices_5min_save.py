"""
Save operations for stock_prices_5min table.
"""
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def convert_to_db_format(
    price_data: Dict[str, str],
    ticker: str,
    timestamp: datetime
) -> Dict[str, Any]:
    """
    Convert Alpha Vantage API price data to database format.
    
    Args:
        price_data: Dict from API with keys: "1. open", "2. high", "3. low", "4. close", "5. volume"
        ticker: Stock ticker symbol
        timestamp: Datetime for this price record (timezone-aware)
        
    Returns:
        Dict with database column names as keys
    """
    # Ensure timestamp is timezone-aware
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    
    # Parse price values (API returns strings)
    try:
        open_price = float(price_data.get("1. open", "0"))
        high_price = float(price_data.get("2. high", "0"))
        low_price = float(price_data.get("3. low", "0"))
        close_price = float(price_data.get("4. close", "0"))
        volume = int(float(price_data.get("5. volume", "0")))
    except (ValueError, TypeError) as e:
        logger.warning(f"Error parsing price data for {ticker} at {timestamp}: {e}")
        return None
    
    db_data = {
        "ticker": ticker.upper(),
        "timestamp": timestamp.isoformat(),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    }
    
    return db_data


def save_price_data(
    supabase: Client,
    ticker: str,
    price_records: List[Dict[str, Any]],
    month: str = None
) -> int:
    """
    Save or update price records in the stock_prices_5min table.
    Uses upsert based on (ticker, timestamp) unique constraint.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker symbol (for logging)
        price_records: List of dicts in database format (from convert_to_db_format)
        month: Month string (YYYY-MM) for logging
        
    Returns:
        Number of records inserted/updated
    """
    if not price_records:
        return 0
    
    if not supabase:
        supabase = get_supabase_client()
    
    month_str = f" (month: {month})" if month else ""
    inserted = 0
    
    # Batch insert/upsert (Supabase handles conflicts via unique constraint)
    # Process in batches to avoid overwhelming the database
    batch_size = 1000
    for i in range(0, len(price_records), batch_size):
        batch = price_records[i:i + batch_size]
        
        try:
            # Upsert using Supabase (ON CONFLICT handled by unique constraint on ticker, timestamp)
            # For composite unique constraints, use comma-separated column names
            result = supabase.table("stock_prices_5min").upsert(
                batch,
                on_conflict="ticker,timestamp"
            ).execute()
            
            if result.data:
                inserted += len(result.data)
        except Exception as e:
            # Handle individual record errors if batch fails
            error_msg = str(e).lower()
            if "duplicate" in error_msg or "unique" in error_msg or "conflict" in error_msg:
                # Try inserting records one by one to identify which ones are duplicates
                logger.debug(f"Batch upsert had conflicts, inserting individually for {ticker}{month_str}")
                for record in batch:
                    try:
                        result = supabase.table("stock_prices_5min").upsert(
                            record,
                            on_conflict="ticker,timestamp"
                        ).execute()
                        if result.data:
                            inserted += len(result.data) if isinstance(result.data, list) else 1
                    except Exception as record_error:
                        # Skip duplicates silently, log other errors
                        record_error_msg = str(record_error).lower()
                        if "duplicate" not in record_error_msg and "unique" not in record_error_msg:
                            logger.warning(f"Error inserting price record for {ticker} at {record.get('timestamp')}: {record_error}")
                        continue
            else:
                logger.error(f"Error upserting price batch for {ticker}{month_str}: {e}")
                continue
    
    logger.info(f"Saved {inserted} price records for {ticker}{month_str} (skipped {len(price_records) - inserted} duplicates)")
    return inserted
