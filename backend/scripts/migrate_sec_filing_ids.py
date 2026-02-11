"""
One-off migration: recreate sec_filings.id and sec_filing_chunks.id using deterministic
bigint from _string_id_to_bigint (same as news_articles). Resumable: only updates rows
that are not yet migrated (current id != target id). Uses batched and parallel updates.

ID strings:
  - sec_filings: sec_filing_{ticker}_{accession_number}
  - sec_filing_chunks: sec_filing_chunk_{ticker}_{accession_number}_{chunk_index}

Run order:
  1. Drop FK (in Supabase SQL or apply migration):
     ALTER TABLE public.sec_filing_chunks DROP CONSTRAINT IF EXISTS sec_filing_chunks_filing_id_fkey;
  2. Run: python -m backend.scripts.migrate_sec_filing_ids [--dry-run]
  3. Re-add FK:
     ALTER TABLE public.sec_filing_chunks ADD CONSTRAINT sec_filing_chunks_filing_id_fkey
       FOREIGN KEY (filing_id) REFERENCES public.sec_filings(id);

Usage: python -m backend.scripts.migrate_sec_filing_ids [--dry-run]
       python -m backend.scripts.migrate_sec_filing_ids --fix-negative-only [--dry-run]  # only fix id < 0 (fast)
"""
import argparse
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.storage.supabase_client import get_supabase_client
from backend.storage.filing_store import filing_string_id, chunk_string_id
from backend.storage.news_articles_save import _string_id_to_bigint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

BATCH = 500
PARALLEL_WORKERS = 20


def _fetch_all(supabase, table: str, select_cols: str = "*", extra_filters=None):
    """Fetch all rows with pagination."""
    out = []
    start = 0
    while True:
        q = supabase.table(table).select(select_cols).range(start, start + BATCH - 1)
        if extra_filters:
            for key, val in extra_filters.items():
                q = q.eq(key, val)
        r = q.execute()
        data = r.data or []
        if not data:
            break
        out.extend(data)
        if len(data) < BATCH:
            break
        start += BATCH
    return out


def _fetch_where_id_negative(supabase, table: str, select_cols: str = "*"):
    """Fetch rows where id < 0 (stuck in temp step)."""
    out = []
    start = 0
    while True:
        q = (
            supabase.table(table)
            .select(select_cols)
            .lt("id", 0)
            .range(start, start + BATCH - 1)
        )
        r = q.execute()
        data = r.data or []
        if not data:
            break
        out.extend(data)
        if len(data) < BATCH:
            break
        start += BATCH
    return out


def run(dry_run: bool = False) -> None:
    supabase = get_supabase_client()

    # 1) All sec_filings, compute target id, keep only those needing update (id != new_id, id > 0)
    filings = _fetch_all(supabase, "sec_filings", "id, ticker, accession_number")
    if not filings:
        logger.info("No sec_filings rows")
        return
    filing_updates: list[tuple[int, int]] = []  # (old_id, new_id)
    old_to_new_filing: dict[int, int] = {}  # for citations: all filings old_id -> new_id
    acc_by_filing_id: dict[int, tuple[str, str]] = {}  # filing_id -> (ticker, accession) for both old and new ids
    for r in filings:
        current_id = int(r["id"])
        ticker = (r.get("ticker") or "").strip().upper()
        acc = (r.get("accession_number") or "").strip()
        new_id = _string_id_to_bigint(filing_string_id(ticker, acc))
        # Map both original and current (possibly negative) id to new_id for citations/acc_by_filing_id
        original_id = current_id if current_id > 0 else -current_id
        old_to_new_filing[original_id] = new_id
        acc_by_filing_id[current_id] = (ticker, acc)
        acc_by_filing_id[new_id] = (ticker, acc)
        acc_by_filing_id[original_id] = (ticker, acc)
        if current_id != new_id:
            # Include positive (not yet migrated) and negative (stuck in temp step)
            filing_updates.append((current_id, new_id))
    logger.info("Filings needing update: %s of %s", len(filing_updates), len(filings))

    # 2) All sec_filing_chunks with filing info; keep only those needing update (id != new_chunk_id, id > 0)
    chunks = _fetch_all(supabase, "sec_filing_chunks", "id, filing_id, ticker, chunk_index")
    chunk_updates: list[tuple[int, int, int]] = []  # (old_chunk_id, new_chunk_id, new_filing_id)
    for r in chunks:
        old_chunk_id = int(r["id"])
        filing_id = int(r["filing_id"])
        ticker = (r.get("ticker") or "").strip().upper()
        chunk_index = int(r.get("chunk_index") or 0)
        ticker_acc = acc_by_filing_id.get(filing_id)
        if ticker_acc:
            ticker, acc = ticker_acc
        else:
            acc = ""
        new_chunk_id = _string_id_to_bigint(chunk_string_id(ticker, acc, chunk_index))
        new_filing_id = _string_id_to_bigint(filing_string_id(ticker, acc))
        if old_chunk_id != new_chunk_id:
            # Include positive (not yet migrated) and negative (stuck in temp step)
            chunk_updates.append((old_chunk_id, new_chunk_id, new_filing_id))
    logger.info("Chunks needing update: %s of %s", len(chunk_updates), len(chunks))

    if dry_run:
        logger.info("Dry run: would update %s filings, %s chunks, then citations", len(filing_updates), len(chunk_updates))
        return

    if not filing_updates and not chunk_updates:
        logger.info("Nothing to update (all already migrated)")
        # Still run citation update in case only citations were left
    else:
        # 3) Batch update sec_filing_chunks.filing_id: one update per filing (all chunks with that filing_id)
        # Use original id (positive) for matching chunks; chunks still have filing_id = original before we fix filings
        for current_id, new_fid in filing_updates:
            old_fid = current_id if current_id > 0 else -current_id
            try:
                supabase.table("sec_filing_chunks").update({"filing_id": new_fid}).eq("filing_id", old_fid).execute()
            except Exception as e:
                logger.error("Batch update filing_id failed old_fid=%s new_fid=%s: %s", old_fid, new_fid, e)
        logger.info("Done batch updating sec_filing_chunks.filing_id (%s filings)", len(filing_updates))

        # 4) Update sec_filings.id: if current id > 0 do temp (-id) then new_id; if current id < 0 (stuck temp) just set new_id.
        def _update_filing_id(current_id: int, new_id: int) -> None:
            try:
                if current_id > 0:
                    supabase.table("sec_filings").update({"id": -current_id}).eq("id", current_id).execute()
                    supabase.table("sec_filings").update({"id": new_id}).eq("id", -current_id).execute()
                else:
                    supabase.table("sec_filings").update({"id": new_id}).eq("id", current_id).execute()
            except Exception as e:
                logger.error("Update sec_filings id current_id=%s new_id=%s: %s", current_id, new_id, e)

        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            futures = [executor.submit(_update_filing_id, current_id, new_id) for current_id, new_id in filing_updates]
            for f in as_completed(futures):
                f.result()
        logger.info("Done updating sec_filings.id")

        # 5) Update sec_filing_chunks.id: if id > 0 do temp (-id) then new_cid; if id < 0 (stuck temp) just set new_cid.
        def _update_chunk_id(current_cid: int, new_cid: int) -> None:
            try:
                if current_cid > 0:
                    supabase.table("sec_filing_chunks").update({"id": -current_cid}).eq("id", current_cid).execute()
                    supabase.table("sec_filing_chunks").update({"id": new_cid}).eq("id", -current_cid).execute()
                else:
                    supabase.table("sec_filing_chunks").update({"id": new_cid}).eq("id", current_cid).execute()
            except Exception as e:
                logger.error("Update chunk id current_cid=%s new_cid=%s: %s", current_cid, new_cid, e)

        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            futures = [
                executor.submit(_update_chunk_id, current_cid, new_cid)
                for current_cid, new_cid, _ in chunk_updates
            ]
            for f in as_completed(futures):
                f.result()
        logger.info("Done updating sec_filing_chunks.id")

    # Step 6 (storyline citations) removed; deprecated table no longer used.


def run_fix_negative_only(dry_run: bool = False) -> None:
    """
    Fix only rows with negative id (stuck in temp step). Much faster than full migration.
    """
    supabase = get_supabase_client()

    filings_neg = _fetch_where_id_negative(supabase, "sec_filings", "id, ticker, accession_number")
    chunks_neg = _fetch_where_id_negative(supabase, "sec_filing_chunks", "id, filing_id, ticker, chunk_index")

    if not filings_neg and not chunks_neg:
        logger.info("No negative ids found in sec_filings or sec_filing_chunks")
        return

    logger.info("Found %s sec_filings and %s sec_filing_chunks with id < 0", len(filings_neg), len(chunks_neg))

    if dry_run:
        logger.info("Dry run: would fix %s filings, %s chunks", len(filings_neg), len(chunks_neg))
        return

    # 1) Fix sec_filings: set id to new_id where id < 0; update sec_filing_chunks.filing_id from old_fid to new_fid
    acc_by_new_fid: dict[int, tuple[str, str]] = {}
    for r in filings_neg:
        current_id = int(r["id"])
        ticker = (r.get("ticker") or "").strip().upper()
        acc = (r.get("accession_number") or "").strip()
        new_id = _string_id_to_bigint(filing_string_id(ticker, acc))
        acc_by_new_fid[new_id] = (ticker, acc)
        try:
            supabase.table("sec_filings").update({"id": new_id}).eq("id", current_id).execute()
            old_fid = -current_id
            supabase.table("sec_filing_chunks").update({"filing_id": new_id}).eq("filing_id", old_fid).execute()
            logger.debug("Fixed sec_filings id %s -> %s", current_id, new_id)
        except Exception as e:
            logger.error("Fix sec_filings id %s -> %s: %s", current_id, new_id, e)
    logger.info("Fixed %s sec_filings (and their chunk filing_id)", len(filings_neg))

    # 2) Fix sec_filing_chunks: set id to new_chunk_id where id < 0 (chunk.filing_id may be new_fid after step 1 or unchanged)
    # Fill (ticker, acc) for any filing_id we don't have yet (chunk's filing was already migrated)
    missing_fids = {int(r["filing_id"]) for r in chunks_neg if acc_by_new_fid.get(int(r["filing_id"])) is None}
    for fid in missing_fids:
        try:
            row = supabase.table("sec_filings").select("ticker, accession_number").eq("id", fid).limit(1).execute()
            if row.data and len(row.data) > 0:
                t = (row.data[0].get("ticker") or "").strip().upper()
                a = (row.data[0].get("accession_number") or "").strip()
                acc_by_new_fid[fid] = (t, a)
        except Exception as e:
            logger.warning("Could not fetch filing %s for chunk: %s", fid, e)
    for r in chunks_neg:
        current_cid = int(r["id"])
        filing_id = int(r["filing_id"])
        ticker = (r.get("ticker") or "").strip().upper()
        chunk_index = int(r.get("chunk_index") or 0)
        ticker_acc = acc_by_new_fid.get(filing_id)
        if ticker_acc:
            ticker, acc = ticker_acc
        else:
            acc = ""
        new_cid = _string_id_to_bigint(chunk_string_id(ticker, acc, chunk_index))
        try:
            supabase.table("sec_filing_chunks").update({"id": new_cid}).eq("id", current_cid).execute()
            logger.debug("Fixed sec_filing_chunks id %s -> %s", current_cid, new_cid)
        except Exception as e:
            logger.error("Fix sec_filing_chunks id %s -> %s: %s", current_cid, new_cid, e)
    logger.info("Fixed %s sec_filing_chunks", len(chunks_neg))


def main():
    p = argparse.ArgumentParser(description="Migrate sec_filings and sec_filing_chunks to deterministic bigint ids (resumable)")
    p.add_argument("--dry-run", action="store_true", help="Only log what would be done")
    p.add_argument("--fix-negative-only", action="store_true", help="Only fix rows with id < 0 (stuck in temp step); much faster")
    args = p.parse_args()
    if args.fix_negative_only:
        run_fix_negative_only(dry_run=args.dry_run)
    else:
        run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
    sys.exit(0)
