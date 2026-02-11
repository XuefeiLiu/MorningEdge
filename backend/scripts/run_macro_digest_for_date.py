"""
Run macro digest for a single date: raw collection → macro_raw_items, then synthesis → per-asset brief tables (macro_brief_fx, …, macro_brief_policy).

Usage:
  python -m backend.scripts.run_macro_digest_for_date
  python -m backend.scripts.run_macro_digest_for_date --date 2026-01-30

Requires ALPHA_VANTAGE_API_KEY (raw), OPENAI_API_KEY (synthesis).
"""
import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run macro digest (raw + synthesis) for a date")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date YYYY-MM-DD (default: yesterday UTC)",
    )
    args = parser.parse_args()

    if args.date:
        try:
            as_of = datetime.strptime(args.date.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            logger.error("Invalid --date; use YYYY-MM-DD")
            sys.exit(1)
    else:
        as_of = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    logger.info("Macro digest for %s", as_of)
    print(f"[macro digest] Date: {as_of}")

    from backend.macro.collect_raw import collect_and_save_raw
    from backend.macro.synthesis import run_synthesis_sync
    from backend.storage.supabase_client import get_supabase_client

    supabase = get_supabase_client()

    print("[macro digest] Step 1/2: Collecting raw items (fetch → dedupe → route → save)...")
    logger.info("Step 1/2: Collecting raw items")
    raw_count = collect_and_save_raw(as_of, supabase=supabase)
    print(f"[macro digest] Step 1/2 done: {raw_count} raw items saved")
    logger.info("Raw items saved: %d", raw_count)

    print("[macro digest] Step 2/3: Synthesizing 8 topic briefs (LLM calls)...")
    logger.info("Step 2/3: Synthesizing briefs")
    brief_count = run_synthesis_sync(as_of, supabase=supabase)
    print(f"[macro digest] Step 2/3 done: {brief_count} briefs saved")
    logger.info("Briefs saved: %d", brief_count)

    print("[macro digest] Step 3/3: Synthesizing daily summary of summaries (LLM)...")
    logger.info("Step 3/3: Daily summary")
    from backend.macro.daily_summary import run_synthesize_daily_summary_sync
    daily_summary_id = run_synthesize_daily_summary_sync(as_of, supabase=supabase)
    print(f"[macro digest] Step 3/3 done: daily summary {'saved' if daily_summary_id else 'skipped/failed'}")
    logger.info("Daily summary saved: %s", bool(daily_summary_id))

    print(f"[macro digest] Complete. Raw: {raw_count}, Briefs: {brief_count}, Daily summary: {'yes' if daily_summary_id else 'no'}")


if __name__ == "__main__":
    main()
