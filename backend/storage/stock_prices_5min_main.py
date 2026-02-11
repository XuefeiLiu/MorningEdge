"""
Main function for fetching and storing 5-minute intraday stock prices from Alpha Vantage API.
Collects data for NASDAQ 100 stocks from 2025-01-01 to 2026-01-31 (13 months).
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional
import httpx
import pytz

from backend.storage.supabase_client import get_supabase_client
from backend.storage.stocks_query import get_all_stocks
from backend.storage.stock_prices_5min_save import convert_to_db_format, save_price_data
from backend.config import ALPHA_VANTAGE_API_KEY, ALPHA_VANTAGE_BASE_URL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Suppress httpx INFO logs
logging.getLogger("httpx").setLevel(logging.ERROR)

# Request delay to be respectful to API (reduced for premium tier)
REQUEST_DELAY = 0.5  # Seconds between requests


def generate_month_list(start_year: int, start_month: int, end_year: int, end_month: int) -> List[str]:
    """
    Generate list of month strings in YYYY-MM format.
    
    Args:
        start_year: Start year
        start_month: Start month (1-12)
        end_year: End year
        end_month: End month (1-12)
        
    Returns:
        List of month strings like ["2024-01", "2024-02", ...]
    """
    months = []
    current_year = start_year
    current_month = start_month
    
    while (current_year < end_year) or (current_year == end_year and current_month <= end_month):
        months.append(f"{current_year:04d}-{current_month:02d}")
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1
    
    return months


def parse_timestamp(timestamp_str: str, timezone_str: str = "US/Eastern") -> datetime:
    """
    Parse timestamp string from Alpha Vantage API to datetime object.
    API returns timestamps in US/Eastern timezone.
    
    Args:
        timestamp_str: Timestamp string in format "YYYY-MM-DD HH:MM:SS"
        timezone_str: Timezone string (default: "US/Eastern")
        
    Returns:
        Datetime object in UTC
    """
    try:
        # Parse the timestamp string
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        
        # Convert from US/Eastern to UTC
        eastern_tz = pytz.timezone(timezone_str)
        dt_eastern = eastern_tz.localize(dt)
        dt_utc = dt_eastern.astimezone(pytz.UTC)
        
        return dt_utc
    except Exception as e:
        logger.error(f"Error parsing timestamp '{timestamp_str}': {e}")
        raise


async def fetch_intraday_data(
    client: httpx.AsyncClient,
    ticker: str,
    month: str,
    api_key: str
) -> Optional[Dict]:
    """
    Fetch intraday data from Alpha Vantage API for a specific ticker and month.
    
    Args:
        client: HTTP client
        ticker: Stock ticker symbol
        month: Month string in YYYY-MM format
        api_key: Alpha Vantage API key
        
    Returns:
        Parsed data dict with 'meta' and 'time_series' keys, or None on error
    """
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": ticker,
        "interval": "5min",
        "outputsize": "full",
        "month": month,
        "apikey": api_key
    }
    
    try:
        response = await client.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        
        # Check for API errors
        if "Error Message" in data:
            logger.error(f"Alpha Vantage API error for {ticker} {month}: {data['Error Message']}")
            return None
        
        if "Note" in data:
            logger.warning(f"Alpha Vantage API note for {ticker} {month}: {data['Note']}")
            # This usually means rate limit exceeded
            return None
        
        # Validate response structure
        if "Meta Data" not in data:
            logger.warning(f"No Meta Data in response for {ticker} {month}")
            return None
        
        meta_data = data["Meta Data"]
        time_series_key = "Time Series (5min)"
        
        if time_series_key not in data:
            logger.warning(f"No time series data in response for {ticker} {month}")
            return None
        
        time_series = data[time_series_key]
        
        return {
            "meta": meta_data,
            "time_series": time_series
        }
        
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching data for {ticker} {month}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching data for {ticker} {month}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching data for {ticker} {month}: {e}")
        return None


async def process_stock_month(
    client: httpx.AsyncClient,
    supabase,
    ticker: str,
    month: str,
    api_key: str,
    stock_index: int,
    total_stocks: int,
    month_index: int,
    total_months: int
) -> int:
    """
    Process a single stock-month combination: fetch data and save to database.
    
    Args:
        client: HTTP client
        supabase: Supabase client
        ticker: Stock ticker symbol
        month: Month string in YYYY-MM format
        api_key: Alpha Vantage API key
        stock_index: Current stock index (for logging)
        total_stocks: Total number of stocks
        month_index: Current month index (for logging)
        total_months: Total number of months
        
    Returns:
        Number of records saved
    """
    logger.info(
        f"[Stock {stock_index}/{total_stocks}] [Month {month_index}/{total_months}] "
        f"Fetching {ticker} for {month}..."
    )
    
    # Fetch data from API
    data = await fetch_intraday_data(client, ticker, month, api_key)
    
    if not data:
        logger.warning(f"No data returned for {ticker} {month}")
        return 0
    
    # Parse time series data
    time_series = data["time_series"]
    meta_data = data["meta"]
    
    # Get timezone from meta data (default to US/Eastern)
    tz_str = meta_data.get("6. Time Zone", "US/Eastern")
    
    price_records = []
    for timestamp_str, price_data in time_series.items():
        try:
            # Parse timestamp
            timestamp = parse_timestamp(timestamp_str, tz_str)
            
            # Convert to database format
            db_record = convert_to_db_format(price_data, ticker, timestamp)
            
            if db_record:
                price_records.append(db_record)
        except Exception as e:
            logger.warning(f"Error processing record for {ticker} {month} at {timestamp_str}: {e}")
            continue
    
    if not price_records:
        logger.warning(f"No valid price records for {ticker} {month}")
        return 0
    
    # Save to database
    saved_count = save_price_data(supabase, ticker, price_records, month)
    
    logger.info(
        f"[Stock {stock_index}/{total_stocks}] [Month {month_index}/{total_months}] "
        f"{ticker} {month}: Saved {saved_count} records"
    )
    
    return saved_count


async def main():
    """
    Main function to collect intraday price data for all NASDAQ 100 stocks.
    """
    logger.info("=" * 60)
    logger.info("Starting 5-minute intraday price data collection")
    logger.info("=" * 60)
    
    # Check API key
    if not ALPHA_VANTAGE_API_KEY:
        logger.error("ALPHA_VANTAGE_API_KEY not configured in .env")
        return
    
    # Connect to Supabase
    try:
        supabase = get_supabase_client()
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        return
    
    # Get all stocks from database
    try:
        stocks = get_all_stocks(supabase)
        tickers = [stock["ticker"] for stock in stocks]
        logger.info(f"Found {len(tickers)} stocks in database")
        
        if not tickers:
            logger.warning("No stocks found in database. Please run stocks_main.py first.")
            return
    except Exception as e:
        logger.error(f"Error fetching stocks: {e}")
        return
    
    # Generate month list (2025-01 to 2026-01)
    months = generate_month_list(2025, 1, 2026, 1)
    logger.info(f"Collecting data for {len(months)} months: {months[0]} to {months[-1]}")
    
    # Track API usage
    total_requests = 0
    total_saved = 0
    failed_combinations = []
    total_combinations = len(tickers) * len(months)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for stock_idx, ticker in enumerate(tickers, start=1):
            for month_idx, month in enumerate(months, start=1):
                try:
                    # Process stock-month combination
                    saved_count = await process_stock_month(
                        client, supabase, ticker, month, ALPHA_VANTAGE_API_KEY,
                        stock_idx, len(tickers), month_idx, len(months)
                    )
                    
                    total_requests += 1
                    total_saved += saved_count
                    
                    # Small delay between requests to be respectful to API
                    await asyncio.sleep(REQUEST_DELAY)
                    
                except Exception as e:
                    logger.error(f"Error processing {ticker} {month}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    failed_combinations.append(f"{ticker} {month}")
                    continue
    
    # Summary
    logger.info("=" * 60)
    logger.info("Collection Summary:")
    logger.info(f"  Total stocks: {len(tickers)}")
    logger.info(f"  Total months: {len(months)}")
    logger.info(f"  Total combinations: {total_combinations}")
    logger.info(f"  Processed: {total_requests}")
    logger.info(f"  Total API requests: {total_requests}")
    logger.info(f"  Total records saved: {total_saved}")
    logger.info(f"  Failed combinations: {len(failed_combinations)}")
    if failed_combinations:
        logger.warning(f"  Failed: {', '.join(failed_combinations[:10])}{'...' if len(failed_combinations) > 10 else ''}")
    
    remaining_combinations = total_combinations - total_requests
    if remaining_combinations > 0:
        logger.info(f"  Remaining combinations: {remaining_combinations}")
        logger.info("  Collection incomplete. Re-run script to continue.")
    else:
        logger.info("  Collection complete!")
    
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
