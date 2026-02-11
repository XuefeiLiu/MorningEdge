"""
Backfill macro topic briefs with macro book RAG. For each date in range, re-runs
synthesis for all 8 topics (FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy,
Monetary Policy, Trump) so that briefs are generated with KB excerpts. Existing
briefs are overwritten (upsert by as_of_date). Requires macro_raw_items populated
for each date and macro_kb_chunks ingested (run ingest_macro_kb first). Uses
OPENAI_API_KEY.

Usage:
  python -m backend.scripts.backfill_macro_briefs_kb --start 2026-01-01 --end 2026-01-31
  python -m backend.scripts.backfill_macro_briefs_kb --start 2026-01-01 --end 2026-01-31 --skip-no-raw
  python -m backend.scripts.backfill_macro_briefs_kb --days 7
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.macro.synthesis import synthesize_all_topics
from backend.storage.macro_raw_items_query import get_raw_items_for_date
from backend.storage.supabase_client import get_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def run_backfill(
    start: date,
    end: date,
    skip_no_raw: bool,
) -> tuple:
    """Run backfill in one event loop; returns (total, saved, skipped_no_raw, failed)."""
    supabase = get_supabase_client()
    llm_client, llm_model = None, None
    try:
        from backend.macro.synthesis import _get_llm_client_and_model
        llm_client, llm_model = _get_llm_client_and_model()
    except ValueError as e:
        logger.warning("LLM not configured: %s", e)

    if llm_client is None or llm_model is None:
        logger.error("Set OPENAI_API_KEY")
        return (0, 0, 0, 0)

    total = saved = skipped_no_raw = failed = 0
    d = start
    while d <= end:
        total += 1
        if skip_no_raw:
            raw_count = len(get_raw_items_for_date(supabase, d, topic=None, limit=1))
            if raw_count == 0:
                skipped_no_raw += 1
                logger.info("%s: no raw items, skip (use without --skip-no-raw to run anyway)", d)
                d += timedelta(days=1)
                continue
        try:
            count = await synthesize_all_topics(
                d,
                supabase=supabase,
                llm_client=llm_client,
                llm_model=llm_model,
                use_cross_topic=True,
            )
            if count and count > 0:
                saved += 1
                logger.info("%s: %d briefs saved", d, count)
            else:
                failed += 1
                logger.warning("%s: synthesis returned 0", d)
        except Exception as e:
            failed += 1
            logger.exception("%s: failed: %s", d, e)
        d += timedelta(days=1)

    return (total, saved, skipped_no_raw, failed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill macro topic briefs with macro book RAG (re-run synthesis for date range)"
    )
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument("--days", type=int, default=None, help="Number of days back from end (alternative to --start)")
    parser.add_argument(
        "--skip-no-raw",
        action="store_true",
        help="Skip dates that have no macro_raw_items (saves LLM cost)",
    )
    args = parser.parse_args()

    if args.days is not None:
        end_d = date.today()
        start_d = end_d - timedelta(days=args.days - 1)
    elif args.start and args.end:
        try:
            start_d = date.fromisoformat(args.start.strip()[:10])
            end_d = date.fromisoformat(args.end.strip()[:10])
        except ValueError:
            logger.error("Invalid --start or --end; use YYYY-MM-DD")
            sys.exit(1)
        if start_d > end_d:
            start_d, end_d = end_d, start_d
    else:
        logger.error("Provide --start and --end, or --days")
        sys.exit(1)

    total, saved, skipped_no_raw, failed = asyncio.run(run_backfill(start_d, end_d, args.skip_no_raw))

    print(
        f"[backfill briefs KB] Done. Total: {total}, saved: {saved}, skipped (no raw): {skipped_no_raw}, failed: {failed}"
    )
    logger.info(
        "Backfill briefs KB complete: total=%d saved=%d skipped_no_raw=%d failed=%d",
        total, saved, skipped_no_raw, failed,
    )


if __name__ == "__main__":
    main()
