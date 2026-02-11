"""
Batch load macro articles day by day from a date range.
Processes each day sequentially with delays to respect API limits.
"""
import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.storage.macro_articles_main import main

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/macro_articles_batch_load.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)


async def batch_load_macro_articles(
    start_date_str: str,
    end_date_str: str,
    delay_between_days: float = 3.0,
    skip_existing: bool = False
):
    """
    Load macro articles day by day for a date range.
    
    Args:
        start_date_str: Start date in YYYY-MM-DD format
        end_date_str: End date in YYYY-MM-DD format
        delay_between_days: Delay in seconds between processing each day (default: 3.0)
        skip_existing: If True, skip days that already have data in database (default: False)
    """
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError as e:
        logger.error(f"Invalid date format. Use YYYY-MM-DD format. Error: {e}")
        return
    
    if start_date > end_date:
        logger.error(f"Start date ({start_date_str}) must be before or equal to end date ({end_date_str})")
        return
    
    # Make timezone-aware
    start_date = start_date.replace(tzinfo=timezone.utc)
    end_date = end_date.replace(tzinfo=timezone.utc)
    
    # Calculate total days
    current_date = start_date
    total_days = (end_date - start_date).days + 1
    
    logger.info("=" * 80)
    logger.info(f"Starting batch load of macro articles")
    logger.info(f"  Date range: {start_date_str} to {end_date_str}")
    logger.info(f"  Total days: {total_days}")
    logger.info(f"  Delay between days: {delay_between_days} seconds")
    logger.info(f"  Skip existing: {skip_existing}")
    logger.info("=" * 80)
    
    successful_days = 0
    failed_days = 0
    skipped_days = 0
    
    day_count = 0
    
    while current_date <= end_date:
        day_count += 1
        date_str = current_date.strftime("%Y-%m-%d")
        
        logger.info("")
        logger.info("-" * 80)
        logger.info(f"Processing day {day_count}/{total_days}: {date_str}")
        logger.info("-" * 80)
        
        # Check if we should skip this day (if skip_existing is enabled)
        if skip_existing:
            # TODO: Add check to see if data already exists for this date
            # For now, we'll process all days
            pass
        
        try:
            # Set start and end to the same day (00:00:00 to 23:59:59)
            day_start = current_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = current_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            # Collect macro news for this day
            results = await main(start_date=day_start, end_date=day_end)
            
            if results and results.get("inserted_count", 0) >= 0:
                successful_days += 1
                logger.info(f"✓ Successfully processed {date_str}: {results.get('inserted_count', 0)} articles inserted")
            else:
                failed_days += 1
                logger.warning(f"✗ Failed to process {date_str}: No results returned")
                
        except Exception as e:
            failed_days += 1
            logger.error(f"✗ Error processing {date_str}: {e}", exc_info=True)
        
        # Move to next day
        current_date += timedelta(days=1)
        
        # Add delay before processing next day (except for the last day)
        if current_date <= end_date:
            logger.info(f"Waiting {delay_between_days} seconds before processing next day...")
            await asyncio.sleep(delay_between_days)
    
    # Print final summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("Batch Load Summary:")
    logger.info(f"  Date range: {start_date_str} to {end_date_str}")
    logger.info(f"  Total days processed: {total_days}")
    logger.info(f"  Successful days: {successful_days}")
    logger.info(f"  Failed days: {failed_days}")
    logger.info(f"  Skipped days: {skipped_days}")
    logger.info("=" * 80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Batch load macro articles day by day for a date range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backend.storage.macro_articles_batch_load --start-date 2025-01-01 --end-date 2026-01-28
  python -m backend.storage.macro_articles_batch_load --start-date 2025-01-01 --end-date 2026-01-28 --delay 5.0
  python -m backend.storage.macro_articles_batch_load --start-date 2025-01-01 --end-date 2026-01-28 --skip-existing

Date format: YYYY-MM-DD (e.g., 2025-01-01)
        """
    )
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Delay in seconds between processing each day (default: 3.0)"
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip days that already have data in database (not implemented yet)"
    )
    
    args = parser.parse_args()
    
    # Ensure logs directory exists
    import os
    os.makedirs("logs", exist_ok=True)
    
    # Run batch load
    asyncio.run(batch_load_macro_articles(
        start_date_str=args.start_date,
        end_date_str=args.end_date,
        delay_between_days=args.delay,
        skip_existing=args.skip_existing
    ))
