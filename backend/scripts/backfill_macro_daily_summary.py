"""
Backfill macro_daily_summary for a date range. For each date that has 8 topic briefs,
runs the daily-summary LLM and saves to macro_daily_summary. Skips dates that already
have a row (unless --overwrite). Requires OPENAI_API_KEY.
Uses one event loop for the whole run to avoid "Event loop is closed" on exit.

Usage:
  python -m backend.scripts.backfill_macro_daily_summary --start 2026-01-01 --end 2026-01-31
  python -m backend.scripts.backfill_macro_daily_summary --start 2026-01-01 --end 2026-01-31 --overwrite
  python -m backend.scripts.backfill_macro_daily_summary --days 7
"""
import argparse
import asyncio
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.macro.daily_summary import _get_llm_client_and_model, synthesize_daily_summary
from backend.storage.macro_brief_by_asset_query import get_all_briefs_for_date
from backend.storage.macro_daily_summary_query import get_daily_summary_for_date
from backend.storage.supabase_client import get_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def run_backfill(start: date, end: date, overwrite: bool) -> tuple:
    """Run backfill in one event loop; returns (total, saved, skipped, no_briefs, failed)."""
    supabase = get_supabase_client()
    llm_client, llm_model = None, None
    try:
        llm_client, llm_model = _get_llm_client_and_model()
    except ValueError:
        pass

    total = saved = skipped = no_briefs = failed = 0
    dates_no_briefs: list[date] = []
    d = start
    while d <= end:
        total += 1
        briefs = get_all_briefs_for_date(supabase, d, topic=None, full=False)
        if not briefs:
            no_briefs += 1
            dates_no_briefs.append(d)
            logger.info("%s: no topic briefs, skip", d)
            d += timedelta(days=1)
            continue
        existing = get_daily_summary_for_date(supabase, d)
        if existing and not overwrite:
            skipped += 1
            logger.info("%s: daily summary exists, skip (use --overwrite to replace)", d)
            d += timedelta(days=1)
            continue
        try:
            row_id = await synthesize_daily_summary(
                d, supabase=supabase, llm_client=llm_client, llm_model=llm_model
            )
            if row_id:
                saved += 1
                logger.info("%s: daily summary saved", d)
            else:
                failed += 1
                logger.warning("%s: daily summary save returned None", d)
        except Exception as e:
            failed += 1
            logger.exception("%s: failed: %s", d, e)
        d += timedelta(days=1)

    return (total, saved, skipped, no_briefs, failed, dates_no_briefs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill macro_daily_summary for a date range")
    parser.add_argument("--start", type=str, default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument("--days", type=int, default=None, help="Number of days back from end (alternative to --start)")
    parser.add_argument("--overwrite", action="store_true", help="Re-run and overwrite existing daily summary rows")
    args = parser.parse_args()

    if args.days is not None:
        end = date.today()
        start = end - timedelta(days=args.days - 1)
    elif args.start and args.end:
        try:
            start = date.fromisoformat(args.start.strip()[:10])
            end = date.fromisoformat(args.end.strip()[:10])
        except ValueError:
            logger.error("Invalid --start or --end; use YYYY-MM-DD")
            sys.exit(1)
        if start > end:
            start, end = end, start
    else:
        logger.error("Provide --start and --end, or --days")
        sys.exit(1)

    total, saved, skipped, no_briefs, failed, dates_no_briefs = asyncio.run(run_backfill(start, end, args.overwrite))

    print(f"[backfill] Done. Total: {total}, saved: {saved}, skipped (existing): {skipped}, no briefs: {no_briefs}, failed: {failed}")
    if dates_no_briefs:
        print(f"[backfill] Dates with no topic briefs (run macro digest first): {[str(d) for d in dates_no_briefs]}")
    logger.info("Backfill complete: total=%d saved=%d skipped=%d no_briefs=%d failed=%d", total, saved, skipped, no_briefs, failed)


if __name__ == "__main__":
    main()
