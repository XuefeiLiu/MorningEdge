"""
Main function for fetching and storing news articles.
"""
import asyncio
import argparse
import logging
import time
import os
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler

from backend.storage.supabase_client import get_supabase_client
from backend.storage.stocks_query import get_all_stocks
from backend.storage.news_collectors import fetch_news_alpha_vantage_range, fetch_news_massive_range
from backend.storage.news_articles_save import convert_to_db_format, save_articles
from backend.storage.embedding_utils import get_embeddings
from backend.services.news_filters import OpenAIFilter

# Configure logging to both console and file
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
log_file = "news_articles.log"

# Create logs directory if it doesn't exist
logs_dir = "logs"
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Full path to log file
log_file_path = os.path.join(logs_dir, log_file)

# Set up root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
root_logger.handlers = []

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(log_format))
root_logger.addHandler(console_handler)

# Force immediate flushing for real-time log viewing
class FlushingFileHandler(RotatingFileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

# File handler with rotation (max 10MB per file, keep 5 backup files) - with immediate flushing
file_handler = FlushingFileHandler(
    log_file_path,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(log_format))
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)
logger.info(f"Logging to console and file: {log_file_path}")

# Suppress httpx INFO logs (only log errors, not successful 200 OK requests)
logging.getLogger("httpx").setLevel(logging.ERROR)

# Uncomment for more detailed debugging:
# logging.getLogger().setLevel(logging.DEBUG)
# logging.getLogger("backend.storage").setLevel(logging.DEBUG)

# Enable asyncio debug mode (helps with async debugging)
# asyncio.get_event_loop().set_debug(True)  # Uncomment if needed


async def main(start_date: datetime = None, end_date: datetime = None):
    """
    Fetch and store news for all stocks in database.
    Fetches news for a date range.
    
    Args:
        start_date: Start date for the date range (timezone-aware datetime). If None, uses 5 days before end_date.
        end_date: End date for the date range (timezone-aware datetime). If None, uses yesterday.
    """
    # Get date range (default: last 5 business days ending yesterday)
    if end_date is None:
        end_date = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999) - timedelta(days=1)
    
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    
    if start_date is None:
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=4)  # 5 days total
    else:
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    logger.info(f"Starting news fetch and store for date range: {start_str} to {end_str}")
    
    # Split date range into 15-day buckets (API limit)
    date_buckets = []
    current_start = start_date
    
    while current_start < end_date:
        # Calculate bucket end date (15 days from start, or end_date if smaller)
        bucket_end = min(
            current_start + timedelta(days=14),  # 15 days total (0-14 = 15 days)
            end_date
        )
        date_buckets.append((current_start, bucket_end))
        
        # Move to next bucket (start from day after current bucket end)
        current_start = bucket_end + timedelta(seconds=1)  # Start of next day
    
    logger.info(f"Split date range into {len(date_buckets)} bucket(s) of ~15 days each (to respect API limits)")
    
    # Connect to Supabase
    try:
        supabase = get_supabase_client()
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        return
    
    try:
        # Get all stocks from database
        logger.info("Fetching stocks from database...")
        stocks = get_all_stocks(supabase)
        tickers = [stock["ticker"] for stock in stocks]
        logger.info(f"Found {len(tickers)} stocks in database")
        
        if not tickers:
            logger.warning("No stocks found in database. Please run stocks_main.py first.")
            return
        
        # Initialize OpenAI filter for relevance checking
        logger.info("Initializing OpenAI filter...")
        news_filter = OpenAIFilter(use_fallback=True)
        if not news_filter.use_ai:
            logger.warning("OpenAI filter not available, will use keyword fallback")
        else:
            logger.info("OpenAI filter initialized successfully")
        
        # Process each date bucket
        total_inserted = {"alpha_vantage": 0, "massive": 0}
        total_filtered = {"alpha_vantage": 0, "massive": 0}
        failed_tickers = []
        
        for bucket_idx, (bucket_start, bucket_end) in enumerate(date_buckets, 1):
            bucket_start_str = bucket_start.strftime("%Y-%m-%d")
            bucket_end_str = bucket_end.strftime("%Y-%m-%d")
            logger.info("=" * 60)
            logger.info(f"Processing date bucket {bucket_idx}/{len(date_buckets)}: {bucket_start_str} to {bucket_end_str}")
            logger.info("=" * 60)
            
            for i, ticker in enumerate(tickers, start=1):
                try:
                    logger.info(f"[{i}/{len(tickers)}] Processing {ticker} for bucket {bucket_idx}...")
                    
                    # Fetch from Alpha Vantage (15-day bucket only)
                    logger.debug(f"Fetching Alpha Vantage news for {ticker}...")
                    av_news = await fetch_news_alpha_vantage_range(ticker, bucket_start, bucket_end)
                    logger.debug(f"Alpha Vantage returned {len(av_news) if av_news else 0} items for {ticker}")
                    av_count = 0
                    if av_news:
                        # Filter news items for relevance to the ticker
                        logger.info(f"Filtering {len(av_news)} Alpha Vantage news items for {ticker}...")
                        filtered_av_news = await news_filter.filter(av_news, ticker)
                        total_filtered["alpha_vantage"] += len(av_news) - len(filtered_av_news)
                        logger.info(f"Filtered to {len(filtered_av_news)} relevant items for {ticker}")
                        
                        if filtered_av_news:
                            # Get embeddings for summaries (fallback to title if summary is None)
                            logger.info(f"Getting embeddings for {len(filtered_av_news)} Alpha Vantage items...")
                            summary_texts = [item.summary or item.title for item in filtered_av_news]
                            embeddings = await get_embeddings(summary_texts)
                            
                            # Add embeddings to NewsItem objects
                            if embeddings is not None and len(embeddings) == len(filtered_av_news):
                                for i, item in enumerate(filtered_av_news):
                                    item.embedding = embeddings[i].tolist()
                                logger.info(f"Added embeddings to {len(filtered_av_news)} Alpha Vantage items")
                            else:
                                logger.warning(f"Failed to get embeddings for Alpha Vantage items, continuing without embeddings")
                            
                            db_items = [convert_to_db_format(item, ticker) for item in filtered_av_news]
                            av_count = save_articles(supabase, ticker, db_items, source="Alpha Vantage", start_date=bucket_start, end_date=bucket_end)
                            total_inserted["alpha_vantage"] += av_count
                    
                    # Fetch from Massive (15-day bucket only)
                    logger.info(f"Fetching Massive news for {ticker}...")
                    massive_news = await fetch_news_massive_range(ticker, bucket_start, bucket_end)
                    logger.info(f"Massive returned {len(massive_news) if massive_news else 0} items for {ticker}")
                    massive_count = 0
                    if massive_news:
                        # Filter news items for relevance to the ticker
                        logger.info(f"Filtering {len(massive_news)} Massive news items for {ticker}...")
                        filtered_massive_news = await news_filter.filter(massive_news, ticker)
                        total_filtered["massive"] += len(massive_news) - len(filtered_massive_news)
                        logger.info(f"Filtered to {len(filtered_massive_news)} relevant items for {ticker}")
                        
                        if filtered_massive_news:
                            # Get embeddings for summaries (fallback to title if summary is None)
                            logger.info(f"Getting embeddings for {len(filtered_massive_news)} Massive items...")
                            summary_texts = [item.summary or item.title for item in filtered_massive_news]
                            embeddings = await get_embeddings(summary_texts)
                            
                            # Add embeddings to NewsItem objects
                            if embeddings is not None and len(embeddings) == len(filtered_massive_news):
                                for i, item in enumerate(filtered_massive_news):
                                    item.embedding = embeddings[i].tolist()
                                logger.info(f"Added embeddings to {len(filtered_massive_news)} Massive items")
                            else:
                                logger.warning(f"Failed to get embeddings for Massive items, continuing without embeddings")
                            
                            db_items = [convert_to_db_format(item, ticker) for item in filtered_massive_news]
                            massive_count = save_articles(supabase, ticker, db_items, source="Massive", start_date=bucket_start, end_date=bucket_end)
                            total_inserted["massive"] += massive_count
                    
                    logger.info(
                        f"[{i}/{len(tickers)}] {ticker} (bucket {bucket_idx}): "
                        f"AV={av_count}, Massive={massive_count} articles inserted"
                    )
                    
                    # Rate limiting: wait between tickers
                    if i < len(tickers):
                        time.sleep(1)  # 1 second delay between tickers
                        
                except Exception as e:
                    logger.error(f"Error processing {ticker} in bucket {bucket_idx}: {e}")
                    failed_tickers.append(f"{ticker} (bucket {bucket_idx})")
                    continue
            
            logger.info(f"Completed bucket {bucket_idx}/{len(date_buckets)}: {bucket_start_str} to {bucket_end_str}")
        
        # Summary
        logger.info("=" * 60)
        logger.info("Summary:")
        logger.info(f"  Total tickers processed: {len(tickers)}")
        logger.info(f"  Failed tickers: {len(failed_tickers)}")
        if failed_tickers:
            logger.info(f"  Failed: {', '.join(failed_tickers)}")
        logger.info(f"  Alpha Vantage articles: {total_inserted['alpha_vantage']} (filtered out: {total_filtered['alpha_vantage']})")
        logger.info(f"  Massive articles: {total_inserted['massive']} (filtered out: {total_filtered['massive']})")
        logger.info(f"  Total articles: {sum(total_inserted.values())}")
        logger.info(f"  Total filtered out: {sum(total_filtered.values())}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error in news fetch and store: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        logger.info("News fetch and store complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch and store news articles for stocks in database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python news_articles_main.py                           # Use default date range (last 5 days)
  python news_articles_main.py --start-date 2026-01-20    # From 2026-01-20 to yesterday
  python news_articles_main.py --end-date 2026-01-24      # Last 5 days ending 2026-01-24
  python news_articles_main.py --start-date 2026-01-20 --end-date 2026-01-24  # Specific range

Date format: YYYY-MM-DD (e.g., 2026-01-20)
        """
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (default: 5 days before end-date)"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD format (default: yesterday)"
    )
    
    args = parser.parse_args()
    
    # Parse dates
    parsed_start_date = None
    parsed_end_date = None
    
    if args.end_date:
        try:
            parsed_end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
            parsed_end_date = parsed_end_date.replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
        except ValueError:
            print(f"ERROR: Invalid end-date format '{args.end_date}'. Use YYYY-MM-DD format.")
            exit(1)
    
    if args.start_date:
        try:
            parsed_start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
            parsed_start_date = parsed_start_date.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
        except ValueError:
            print(f"ERROR: Invalid start-date format '{args.start_date}'. Use YYYY-MM-DD format.")
            exit(1)
    
    # Validate date range
    if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
        print(f"ERROR: start-date ({parsed_start_date.date()}) must be before or equal to end-date ({parsed_end_date.date()})")
        exit(1)
    
    asyncio.run(main(start_date=parsed_start_date, end_date=parsed_end_date))
