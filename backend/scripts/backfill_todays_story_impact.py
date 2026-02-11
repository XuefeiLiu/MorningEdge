"""
Backfill impact_level and impact_score for long stories updated or created today only.

- impact_level: NULL -> high.
- impact_score: NULL -> 0.8 so Discover sort works.

See README_scripts.md (Impact section) for how impact is created and when to run this.
Usage:
  python -m backend.scripts.backfill_todays_story_impact
  python -m backend.scripts.backfill_todays_story_impact --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

# project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill impact_level for today's storylines and long stories (NULL only)")
    parser.add_argument("--dry-run", action="store_true", help="Log what would be updated without writing to DB")
    args = parser.parse_args()

    try:
        from backend.storage.supabase_client import get_supabase_client
    except Exception as e:
        logger.error("Supabase client import failed: %s", e)
        sys.exit(1)

    supabase = get_supabase_client()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = datetime.now(timezone.utc)
    today_start_iso = today_start.isoformat()
    today_end_iso = today_end.isoformat()

    def _level_to_score(level: str) -> float:
        v = (level or "").strip().lower()
        if v == "high": return 0.8
        if v == "low": return 0.2
        return 0.5

    updated_long = 0

    # long_stories: updated or created today with impact_level or impact_score NULL
    try:
        long_result = (
            supabase.table("long_stories")
            .select("id, impact_level, impact_score, last_updated_at, created_at")
            .gte("last_updated_at", today_start_iso)
            .lte("last_updated_at", today_end_iso)
            .execute()
        )
        long_rows = long_result.data or []
        long_created = (
            supabase.table("long_stories")
            .select("id, impact_level, impact_score, last_updated_at, created_at")
            .gte("created_at", today_start_iso)
            .lte("created_at", today_end_iso)
            .execute()
        )
        long_created_rows = long_created.data or []
        long_seen = {r["id"] for r in long_rows}
        for r in long_created_rows:
            if r["id"] not in long_seen:
                long_rows.append(r)
                long_seen.add(r["id"])

        null_long = [r for r in long_rows if r.get("impact_level") is None or str(r.get("impact_level")).strip() == ""]

        for r in null_long:
            payload = {"impact_level": "high"}
            if r.get("impact_score") is None:
                payload["impact_score"] = 0.8
            if not args.dry_run:
                supabase.table("long_stories").update(payload).eq("id", r["id"]).execute()
            updated_long += 1

        need_score_long = [r for r in long_rows if r.get("impact_level") is not None and str(r.get("impact_level")).strip() and r.get("impact_score") is None]
        for r in need_score_long:
            if not args.dry_run:
                supabase.table("long_stories").update({"impact_score": _level_to_score(r.get("impact_level"))}).eq("id", r["id"]).execute()

        if args.dry_run and null_long:
            logger.info("[dry-run] Would set impact_level/impact_score for long_stories: %s", len(null_long))
    except Exception as e:
        if "does not exist" in str(e).lower():
            logger.info("long_stories table or column not present: %s", e)
        else:
            logger.warning("long_stories backfill: %s", e)

    logger.info(
        "Today's impact backfill %s: long=%s",
        "dry-run" if args.dry_run else "done",
        updated_long,
    )


if __name__ == "__main__":
    main()
