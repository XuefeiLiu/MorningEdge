"""
Backfill sec_filing_chunks for sec_filings that have no chunks.

Finds sec_filings with zero rows in sec_filing_chunks, then for each:
fetches full text from the filing URL, chunks it, embeds and stores chunks
(using store_filing_chunks with accession_number for deterministic chunk ids).

Run: python -m backend.scripts.backfill_filing_chunks [--tickers TICKER1,TICKER2] [--limit N]
"""
import argparse
import asyncio
import logging
import sys
from typing import List, Optional

from backend.config import FILING_FORMS
from backend.pipeline.filing_chunking import chunk_filing_text
from backend.pipeline.filing_fetch import fetch_filing_full_text
from backend.storage.filing_store import store_filing_chunks
from backend.storage.supabase_client import get_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BATCH = 500


def _fetch_all_filing_ids_with_chunks(supabase) -> set:
    """Return set of filing_id that have at least one chunk."""
    out = set()
    start = 0
    while True:
        r = (
            supabase.table("sec_filing_chunks")
            .select("filing_id")
            .range(start, start + BATCH - 1)
            .execute()
        )
        data = r.data or []
        if not data:
            break
        for row in data:
            fid = row.get("filing_id")
            if fid is not None:
                out.add(int(fid))
        if len(data) < BATCH:
            break
        start += BATCH
    return out


def _fetch_filings_without_chunks(supabase, tickers: Optional[List[str]] = None, limit: Optional[int] = None):
    """Return list of sec_filings rows that have no sec_filing_chunks."""
    with_chunks = _fetch_all_filing_ids_with_chunks(supabase)
    out = []
    start = 0
    while True:
        q = supabase.table("sec_filings").select("id, ticker, accession_number, form_type, filed_date, url")
        if tickers:
            q = q.in_("ticker", [t.strip().upper() for t in tickers])
        r = q.range(start, start + BATCH - 1).execute()
        data = r.data or []
        if not data:
            break
        for row in data:
            if int(row["id"]) not in with_chunks:
                if row.get("form_type") in FILING_FORMS and (row.get("url") or "").strip():
                    out.append(row)
                    if limit and len(out) >= limit:
                        return out
        if len(data) < BATCH:
            break
        start += BATCH
    return out


async def _process_filing(supabase, filing: dict) -> tuple[int, int]:
    """
    Fetch full text, chunk, store for one filing. Returns (chunks_stored, 0) on success, (0, 1) on skip/fail.
    """
    ticker = (filing.get("ticker") or "").strip().upper()
    accession = (filing.get("accession_number") or "").strip()
    form_type = (filing.get("form_type") or "").strip()
    filing_id = int(filing["id"])
    url = (filing.get("url") or "").strip()
    if not url:
        logger.warning("No URL for filing id=%s %s %s", filing_id, ticker, accession)
        return 0, 1
    if form_type not in FILING_FORMS:
        return 0, 0
    filed_date = filing.get("filed_date")
    filed_date_str = filed_date.strftime("%Y-%m-%d") if hasattr(filed_date, "strftime") else str(filed_date or "")[:10]
    full_text = await fetch_filing_full_text(url)
    if not full_text:
        logger.warning("Failed to fetch full text for %s %s %s", ticker, form_type, accession)
        return 0, 1
    chunks = chunk_filing_text(full_text, ticker, form_type, filed_date_str)
    if not chunks:
        logger.warning("No chunks for %s %s %s", ticker, form_type, accession)
        return 0, 1
    try:
        stored = await store_filing_chunks(supabase, filing_id, ticker, chunks, accession_number=accession)
        logger.info("Stored %s chunks for %s %s %s", stored, ticker, form_type, accession)
        return stored, 0
    except Exception as e:
        logger.error("store_filing_chunks failed %s %s: %s", ticker, accession, e)
        return 0, 1


async def run_backfill(
    tickers: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> None:
    supabase = get_supabase_client()
    filings = _fetch_filings_without_chunks(supabase, tickers=tickers, limit=limit)
    if not filings:
        logger.info("No filings without chunks found")
        return
    logger.info("Found %s filings without chunks", len(filings))
    total_stored = 0
    total_fail = 0
    for i, filing in enumerate(filings):
        logger.info("[%s/%s] %s %s", i + 1, len(filings), filing.get("ticker"), filing.get("accession_number"))
        stored, fail = await _process_filing(supabase, filing)
        total_stored += stored
        total_fail += fail
    logger.info("Backfill done: %s chunks stored, %s failures", total_stored, total_fail)


def _parse_ticker_list(value: Optional[str]) -> List[str]:
    if not value or not value.strip():
        return []
    return [t.strip().upper() for t in value.split(",") if t.strip()]


def main():
    p = argparse.ArgumentParser(description="Backfill sec_filing_chunks for filings that have none")
    p.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers (default: all)")
    p.add_argument("--limit", type=int, default=None, help="Max number of filings to process (default: all)")
    args = p.parse_args()
    tickers = _parse_ticker_list(args.tickers) if args.tickers else None
    asyncio.run(run_backfill(tickers=tickers, limit=args.limit))


if __name__ == "__main__":
    main()
    sys.exit(0)
