"""
Daily macro news update module for fetching and storing macro articles for yesterday (day T).
Designed to run daily at 5am T+1 to fetch macro news from day T.
Uses Alpha Vantage NEWS_SENTIMENT API with macro topics (economy_fiscal, economy_monetary, economy_macro).
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from backend.storage.macro_articles_main import collect_macro_news

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
    Fetch and store macro news for a single day (yesterday by default).
    Designed to run at 5am T+1 to fetch macro news from day T.
    
    Args:
        target_date: Target date to fetch news for (timezone-aware datetime). 
                    If None, uses yesterday (day T when run at 5am T+1).
    """
    # Calculate target date (yesterday by default - day T)
    if target_date is None:
        target_date = datetime.now(timezone.utc) - timedelta(days=1)
    
    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=timezone.utc)
    
    # Set time range for the entire day (same logic as news_articles_daily.py)
    start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    date_str = target_date.strftime("%Y-%m-%d")
    logger.info("=" * 60)
    logger.info(f"Daily Macro News Update: Fetching macro news for {date_str} (day T)")
    logger.info("=" * 60)
    
    try:
        # Collect macro news using the main collection function
        results = await collect_macro_news(
            start_date=start_time,
            end_date=end_time,
            api_key=None,  # Uses config ALPHA_VANTAGE_API_KEY
            limit_per_topic=1000,
            delay_between_calls=2.0
        )
        
        # Summary
        logger.info("=" * 60)
        logger.info(f"Daily Macro News Update Summary for {date_str}:")
        logger.info(f"  Date range: {date_str} (00:00:00 to 23:59:59 UTC)")
        logger.info("  Articles by topic:")
        for topic, articles in results["articles_by_topic"].items():
            logger.info(f"    {topic}: {len(articles)} articles")
        logger.info(f"  Total unique articles fetched: {results['total_articles']}")
        logger.info(f"  Articles after relevance filtering: {results.get('filtered_articles', results['total_articles'])}")
        logger.info(f"  Articles filtered out: {results.get('filtered_out_count', 0)}")
        logger.info(f"  Articles after similarity deduplication: {results.get('deduplicated_articles', results.get('filtered_articles', results['total_articles']))}")
        logger.info(f"  Similar articles deduplicated: {results.get('deduplication_count', 0)}")
        logger.info(f"  Articles inserted into database: {results['inserted_count']}")
        logger.info("=" * 60)
        
        return results
        
    except Exception as e:
        logger.error(f"Error in daily macro news update: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise
    finally:
        logger.info(f"Daily macro news update complete for {date_str}")


if __name__ == "__main__":
    asyncio.run(main())
