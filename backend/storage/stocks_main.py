"""
Main function for populating stocks table.
"""
import logging
from backend.storage.supabase_client import get_supabase_client
from backend.storage.nasdaq100_tickers import get_nasdaq100_stocks
from backend.storage.stocks_save import save_stocks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """
    Populate stocks table with NASDAQ 100 stocks.
    """
    logger.info("Starting stocks table population...")
    
    # Get NASDAQ 100 stocks with company info
    logger.info("Fetching NASDAQ 100 stock list...")
    stocks_data = get_nasdaq100_stocks(use_api=False)  # Use hardcoded list for now
    logger.info(f"Found {len(stocks_data)} NASDAQ 100 stocks")
    
    # Connect to Supabase
    try:
        supabase = get_supabase_client()
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        return
    
    try:
        # Save stocks to database
        logger.info("Populating stocks table...")
        saved_count = save_stocks(supabase, stocks_data)
        logger.info(f"Stocks table populated with {saved_count} stocks")
        
        logger.info("=" * 60)
        logger.info("Summary:")
        logger.info(f"  Total stocks processed: {len(stocks_data)}")
        logger.info(f"  Stocks saved: {saved_count}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error populating stocks table: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        logger.info("Stocks population complete")


if __name__ == "__main__":
    main()
