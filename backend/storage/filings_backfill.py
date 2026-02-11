"""
One-time backfill: 10-K/10-Q SEC filings for all tickers, past 5 years.

Run: python -m backend.storage.filings_backfill [--start-date ...] [--end-date ...]
      Omit --tickers to process all tickers; use --tickers AAPL to test one; or --tickers AAPL,MSFT for a list.

Loads all tickers from stocks, fetches SEC 10-K/10-Q metadata, fetches full text (primary only),
chunks, embeds, and stores in sec_filings + sec_filing_chunks.
Skips filings already in sec_filings (by ticker + accession_number).
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from backend.config import (
    FILING_BACKFILL_DAYS,
    FILING_FORMS,
)
from backend.models import SECFiling
from backend.services.collectors.sec_edgar import SECEdgarCollector
from backend.pipeline.filing_fetch import fetch_filing_full_text
from backend.pipeline.filing_chunking import chunk_filing_text
from backend.storage.supabase_client import get_supabase_client
from backend.storage.stocks_query import get_all_stocks
from backend.storage.filing_store import upsert_sec_filing, store_filing_chunks, backfill_filing_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _parse_args():
    p = argparse.ArgumentParser(description="Backfill 10-K/10-Q filings for all tickers")
    p.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD (default: now - FILING_BACKFILL_DAYS)",
    )
    p.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: now)",
    )
    p.add_argument(
        "--metadata-only",
        action="store_true",
        help="Only backfill fiscal_year/period on sec_filings and doc_type/source on sec_filing_chunks",
    )
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        metavar="SYMBOLS",
        help="Ticker list: omit to use all tickers from stocks; use one (e.g. AAPL) to test; or comma-separated (e.g. AAPL,MSFT)",
    )
    p.add_argument(
        "--missing-only",
        action="store_true",
        help="Backfill only tickers that are in stocks but have no rows in sec_filings",
    )
    return p.parse_args()


async def _process_filing(
    supabase,
    filing: SECFiling,
) -> tuple[int, int]:
    """
    Fetch full text, chunk, store. Returns (chunks_stored, 0) on success, (0, 1) on skip/fail.
    """
    ticker = filing.symbol.strip().upper()
    form_type = filing.form_type or ""
    if form_type not in FILING_FORMS:
        return 0, 0
    accession = getattr(filing, "accession_number", None) or ""
    if not accession:
        logger.warning(f"No accession_number for {ticker} {form_type}, skipping")
        return 0, 1
    try:
        existing = (
            supabase.table("sec_filings")
            .select("id")
            .eq("ticker", ticker)
            .eq("accession_number", accession)
            .limit(1)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            logger.info(f"Already have {ticker} {form_type} {accession}, skipping (no re-store)")
            return 0, 0
    except Exception as e:
        logger.warning(f"Check existing failed: {e}")
    full_text = await fetch_filing_full_text(filing.url)
    if not full_text:
        logger.warning(f"Failed to fetch full text for {ticker} {form_type} {accession}")
        return 0, 1
    filed_date_str = filing.filed_date.strftime("%Y-%m-%d") if hasattr(filing.filed_date, "strftime") else str(filing.filed_date)[:10]
    chunks = chunk_filing_text(full_text, ticker, form_type, filed_date_str)
    if not chunks:
        logger.warning(f"No chunks for {ticker} {form_type} {accession}")
        return 0, 1
    filing_id = await upsert_sec_filing(
        supabase,
        ticker=ticker,
        form_type=form_type,
        filed_date=filed_date_str,
        accession_number=accession,
        url=filing.url,
        primary_document=None,
    )
    if filing_id is None:
        logger.warning(f"Failed to upsert sec_filing {ticker} {accession}")
        return 0, 1
    stored = await store_filing_chunks(supabase, filing_id, ticker, chunks, accession_number=accession)
    logger.info(f"Stored {stored} chunks for {ticker} {form_type} {accession}")
    return stored, 0


def _parse_ticker_list(value: Optional[str]) -> List[str]:
    """Parse comma-separated tickers into list of uppercase symbols."""
    if not value or not value.strip():
        return []
    return [t.strip().upper() for t in value.split(",") if t.strip()]


def _get_stocks_without_sec_filings(supabase) -> List[str]:
    """Return tickers that are in stocks but have no rows in sec_filings."""
    all_stocks = get_all_stocks(supabase)
    stock_tickers = { (s.get("ticker") or "").strip().upper() for s in all_stocks if (s.get("ticker") or "").strip() }
    # Paginate sec_filings distinct tickers
    seen_in_filings: set = set()
    start = 0
    batch = 500
    while True:
        r = supabase.table("sec_filings").select("ticker").range(start, start + batch - 1).execute()
        data = r.data or []
        for row in data:
            t = (row.get("ticker") or "").strip().upper()
            if t:
                seen_in_filings.add(t)
        if len(data) < batch:
            break
        start += batch
    # Distinct tickers: we may have duplicates across pages, but that's ok for the set
    missing = sorted(stock_tickers - seen_in_filings)
    return missing


async def run_backfill(
    start_date: datetime,
    end_date: datetime,
    tickers_override: Optional[List[str]] = None,
) -> None:
    supabase = get_supabase_client()
    if tickers_override:
        tickers = tickers_override
        if not tickers:
            logger.error("Invalid --tickers (empty list)")
            return
        logger.info(f"Backfill ({len(tickers)} tickers): {', '.join(tickers)}, {start_date.date()} to {end_date.date()}")
    else:
        all_stocks = get_all_stocks(supabase)
        tickers = [s.get("ticker") or "" for s in all_stocks if s.get("ticker")]
        tickers = [t.strip().upper() for t in tickers if t]
        if not tickers:
            logger.error("No tickers from stocks")
            return
        logger.info(f"Backfill: {len(tickers)} tickers, {start_date.date()} to {end_date.date()}")
    collector = SECEdgarCollector()
    total_chunks = 0
    total_fail = 0
    for i, ticker in enumerate(tickers):
        logger.info(f"[{i+1}/{len(tickers)}] {ticker}...")
        try:
            filings = await collector.collect(
                symbols=[ticker],
                start_time=start_date,
                end_time=end_date,
            )
        except Exception as e:
            logger.error(f"SEC collect failed for {ticker}: {e}")
            total_fail += 1
            continue
        filings_10k_10q = [f for f in filings if f.form_type in FILING_FORMS]
        for filing in filings_10k_10q:
            stored, fail = await _process_filing(supabase, filing)
            total_chunks += stored
            total_fail += fail
    logger.info(f"Backfill done: {total_chunks} chunks stored, {total_fail} failures/skips")


def main():
    args = _parse_args()
    if args.metadata_only:
        supabase = get_supabase_client()
        filings_updated, chunks_updated = backfill_filing_metadata(supabase)
        logger.info(f"Metadata backfill: {filings_updated} filings, {chunks_updated} chunks updated")
        return
    end_date = datetime.now(timezone.utc)
    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.error("Invalid --end-date, use YYYY-MM-DD")
            sys.exit(1)
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.error("Invalid --start-date, use YYYY-MM-DD")
            sys.exit(1)
    else:
        start_date = end_date - timedelta(days=FILING_BACKFILL_DAYS)
    tickers_override = None
    if args.missing_only:
        supabase = get_supabase_client()
        tickers_override = _get_stocks_without_sec_filings(supabase)
        if not tickers_override:
            logger.info("No stocks missing sec_filings; nothing to backfill")
            return
        logger.info("Backfilling %s stocks that have no sec_filings: %s", len(tickers_override), ", ".join(tickers_override))
    elif args.tickers:
        tickers_override = _parse_ticker_list(args.tickers)
    asyncio.run(run_backfill(start_date, end_date, tickers_override=tickers_override))


if __name__ == "__main__":
    main()
