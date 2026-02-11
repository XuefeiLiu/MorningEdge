"""
Script to check if all required (stock, date) combinations exist in the database.
Skips non-trading days (weekends and US market holidays).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Set, Tuple
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.stocks_query import get_all_stocks
from backend.storage.stock_prices_5min_query import check_day_has_data
from backend.utils.us_business_day import is_us_business_day

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def is_trading_day(d: datetime.date) -> bool:
    """
    Check if a date is a trading day (weekday and not a US market holiday).
    Thin wrapper around is_us_business_day for backward compatibility.
    """
    return is_us_business_day(d)


def generate_trading_days(start_date: datetime.date, end_date: datetime.date) -> List[datetime.date]:
    """
    Generate list of trading days between start_date and end_date (inclusive).
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        
    Returns:
        List of trading day dates
    """
    trading_days = []
    current_date = start_date
    
    while current_date <= end_date:
        if is_trading_day(current_date):
            trading_days.append(current_date)
        current_date += timedelta(days=1)
    
    return trading_days


def check_stock_date_combinations(
    supabase: Client,
    tickers: List[str],
    start_date: datetime.date,
    end_date: datetime.date,
    show_progress: bool = True
) -> Tuple[Set[Tuple[str, datetime.date]], Set[Tuple[str, datetime.date]]]:
    """
    Check which (ticker, date) combinations have data and which are missing.
    
    Args:
        supabase: Supabase client instance
        tickers: List of ticker symbols
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        show_progress: Whether to show progress updates
        
    Returns:
        Tuple of (existing_combinations, missing_combinations)
    """
    # Generate trading days
    logger.info(f"Generating trading days from {start_date} to {end_date}...")
    trading_days = generate_trading_days(start_date, end_date)
    logger.info(f"Found {len(trading_days)} trading days")
    
    existing = set()
    missing = set()
    total_combinations = len(tickers) * len(trading_days)
    checked = 0
    
    logger.info(f"Checking {total_combinations} (ticker, date) combinations...")
    
    for ticker in tickers:
        for trading_day in trading_days:
            checked += 1
            
            if show_progress and checked % 100 == 0:
                logger.info(f"Progress: {checked}/{total_combinations} ({checked * 100 // total_combinations}%)")
            
            # Convert date to datetime for query (use noon UTC to avoid timezone issues)
            check_datetime = datetime.combine(trading_day, datetime.min.time()).replace(tzinfo=timezone.utc)
            check_datetime = check_datetime.replace(hour=12, minute=0, second=0)
            
            if check_day_has_data(supabase, ticker, check_datetime):
                existing.add((ticker, trading_day))
            else:
                missing.add((ticker, trading_day))
    
    return existing, missing


def main():
    """
    Main function to check all (stock, date) combinations.
    """
    logger.info("=" * 60)
    logger.info("Stock Prices 5min Data Completeness Check")
    logger.info("=" * 60)
    
    # Date range: 2025-01-01 to 2026-01-31
    start_date = datetime(2025, 1, 1).date()
    end_date = datetime(2026, 1, 31).date()
    
    logger.info(f"Date range: {start_date} to {end_date}")
    
    # Connect to Supabase
    try:
        supabase = get_supabase_client()
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        return
    
    # Get all stocks
    try:
        stocks = get_all_stocks(supabase)
        tickers = [stock["ticker"] for stock in stocks]
        logger.info(f"Found {len(tickers)} stocks in database")
        
        if not tickers:
            logger.warning("No stocks found in database.")
            return
    except Exception as e:
        logger.error(f"Error fetching stocks: {e}")
        return
    
    # Check combinations
    try:
        existing, missing = check_stock_date_combinations(
            supabase, tickers, start_date, end_date
        )
        
        # Summary
        logger.info("=" * 60)
        logger.info("Completeness Check Summary:")
        logger.info(f"  Date range: {start_date} to {end_date}")
        logger.info(f"  Total stocks: {len(tickers)}")
        logger.info(f"  Total trading days: {len(generate_trading_days(start_date, end_date))}")
        logger.info(f"  Total combinations: {len(existing) + len(missing)}")
        logger.info(f"  Existing combinations: {len(existing)} ({len(existing) * 100 // (len(existing) + len(missing))}%)")
        logger.info(f"  Missing combinations: {len(missing)} ({len(missing) * 100 // (len(existing) + len(missing))}%)")
        logger.info("=" * 60)
        
        # Show missing combinations (grouped by ticker)
        if missing:
            logger.warning(f"\nMissing {len(missing)} (ticker, date) combinations:")
            
            # Group by ticker
            missing_by_ticker = {}
            for ticker, date in sorted(missing):
                if ticker not in missing_by_ticker:
                    missing_by_ticker[ticker] = []
                missing_by_ticker[ticker].append(date)
            
            # Show first 20 tickers with missing data
            shown_tickers = 0
            for ticker in sorted(missing_by_ticker.keys()):
                dates = sorted(missing_by_ticker[ticker])
                logger.warning(f"  {ticker}: {len(dates)} missing days")
                if shown_tickers < 5:  # Show details for first 5 tickers
                    logger.warning(f"    Missing dates: {', '.join(str(d) for d in dates[:10])}{'...' if len(dates) > 10 else ''}")
                    shown_tickers += 1
            
            if len(missing_by_ticker) > 5:
                logger.warning(f"    ... and {len(missing_by_ticker) - 5} more tickers with missing data")
        else:
            logger.info("✓ All required combinations are present!")
        
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error checking combinations: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
