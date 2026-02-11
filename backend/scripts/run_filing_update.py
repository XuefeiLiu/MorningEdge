"""
Run SEC filing update only: same logic as store_embed_data filing update (submissions API per ticker).
No daily index — uses SECEdgarCollector per ticker like filings_backfill, so avoids 403 on form.idx.

Usage:
  python -m backend.scripts.run_filing_update
  python -m backend.scripts.run_filing_update --days 60
  python -m backend.scripts.run_filing_update --tickers AAPL,MSFT
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SEC filing update only (submissions API per ticker, same as store_embed_data)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Look back N days for new filings (default: FILING_UPDATE_DAYS env or 60)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers to check (default: all from stocks table)",
    )
    args = parser.parse_args()

    from backend.config import FILING_UPDATE_DAYS
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.stocks_query import get_all_stocks
    from backend.pipeline.store_embed_data import _run_filing_update

    days = args.days if args.days is not None else FILING_UPDATE_DAYS
    now = datetime.now(timezone.utc)
    filing_start = now - timedelta(days=days)
    filing_end = now

    logger.info(
        "Filing update: last %s days (%s to %s)",
        days,
        filing_start.date(),
        filing_end.date(),
    )

    supabase = get_supabase_client()
    if args.tickers:
        ticker_list = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if not ticker_list:
            logger.error("No valid tickers in --tickers")
            return
    else:
        stocks = get_all_stocks(supabase)
        ticker_list = [(s.get("ticker") or "").strip() for s in stocks if (s.get("ticker") or "").strip()]
        ticker_list = [t.upper() for t in ticker_list if t]
    if not ticker_list:
        logger.warning("No tickers to check")
        return

    logger.info("Checking %s tickers via submissions API", len(ticker_list))
    stats = await _run_filing_update(supabase, ticker_list, filing_start, filing_end)
    logger.info(
        "Filing update done: %s new filings, %s chunks stored",
        stats.get("filings_processed", 0),
        stats.get("chunks_stored", 0),
    )
    print(
        f"[filing update] filings_processed={stats.get('filings_processed', 0)} chunks_stored={stats.get('chunks_stored', 0)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
