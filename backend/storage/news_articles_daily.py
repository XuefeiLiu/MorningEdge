"""
Daily news update module for fetching and storing news articles for yesterday (day T).
Designed to run daily at 5am T+1 to fetch news from day T.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

from backend.storage.supabase_client import get_supabase_client
from backend.storage.stocks_query import get_all_stocks
from backend.storage.news_collectors import fetch_news_alpha_vantage_range, fetch_news_massive_range
from backend.storage.news_articles_save import convert_to_db_format, save_articles
from backend.storage.embedding_utils import get_embeddings
from backend.services.news_filters import OpenAIFilter

# Configure logging to console only (for GitHub Actions visibility)
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Set up root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
root_logger.handlers = []

# Console handler (stdout/stderr - visible in GitHub Actions)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(log_format))
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)
logger.info("Logging to console only (visible in GitHub Actions)")

# Suppress httpx INFO logs (only log errors, not successful 200 OK requests)
logging.getLogger("httpx").setLevel(logging.ERROR)


async def main(target_date: datetime = None):
    """
    Fetch and store news for all stocks in database for a single day (yesterday by default).
    Designed to run at 5am T+1 to fetch news from day T.
    
    Args:
        target_date: Target date to fetch news for (timezone-aware datetime). 
                    If None, uses yesterday (day T when run at 5am T+1).
    """
    # Calculate target date (yesterday by default - day T)
    if target_date is None:
        target_date = datetime.now(timezone.utc) - timedelta(days=1)
    
    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=timezone.utc)
    
    # Set time range for the entire day
    start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    date_str = target_date.strftime("%Y-%m-%d")
    logger.info("=" * 60)
    logger.info(f"Daily News Update: Fetching news for {date_str} (day T)")
    logger.info("=" * 60)
    
    # Connect to Supabase
    try:
        supabase = get_supabase_client()
        logger.info("Connected to Supabase")
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
        
        # Process each ticker
        total_inserted = {"alpha_vantage": 0, "massive": 0}
        total_filtered = {"alpha_vantage": 0, "massive": 0}
        failed_tickers = []
        
        for i, ticker in enumerate(tickers, start=1):
            try:
                logger.info(f"[{i}/{len(tickers)}] Processing {ticker} for {date_str}...")
                
                # Fetch from Alpha Vantage
                logger.debug(f"Fetching Alpha Vantage news for {ticker}...")
                av_news = await fetch_news_alpha_vantage_range(ticker, start_time, end_time)
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
                        av_count = save_articles(supabase, ticker, db_items, source="Alpha Vantage", start_date=start_time, end_date=end_time)
                        total_inserted["alpha_vantage"] += av_count
                
                # Fetch from Massive
                logger.info(f"Fetching Massive news for {ticker}...")
                massive_news = await fetch_news_massive_range(ticker, start_time, end_time)
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
                        massive_count = save_articles(supabase, ticker, db_items, source="Massive", start_date=start_time, end_date=end_time)
                        total_inserted["massive"] += massive_count
                
                logger.info(
                    f"[{i}/{len(tickers)}] {ticker}: "
                    f"AV={av_count}, Massive={massive_count} articles inserted"
                )
                
                # Rate limiting: wait between tickers
                if i < len(tickers):
                    time.sleep(1)  # 1 second delay between tickers
                    
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                failed_tickers.append(ticker)
                continue
        
        # Summary
        logger.info("=" * 60)
        logger.info(f"Daily News Update Summary for {date_str}:")
        logger.info(f"  Total tickers processed: {len(tickers)}")
        logger.info(f"  Failed tickers: {len(failed_tickers)}")
        if failed_tickers:
            logger.warning(f"  Failed: {', '.join(failed_tickers)}")
        logger.info(f"  Alpha Vantage articles: {total_inserted['alpha_vantage']} (filtered out: {total_filtered['alpha_vantage']})")
        logger.info(f"  Massive articles: {total_inserted['massive']} (filtered out: {total_filtered['massive']})")
        logger.info(f"  Total articles: {sum(total_inserted.values())}")
        logger.info(f"  Total filtered out: {sum(total_filtered.values())}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error in daily news update: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise
    finally:
        logger.info(f"Daily news update complete for {date_str}")


if __name__ == "__main__":
    asyncio.run(main())
