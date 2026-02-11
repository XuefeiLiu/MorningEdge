"""
Remove all long stories from long_stories and their links from long_story_article_links.

Long stories live in long_stories; links in long_story_article_links. This script deletes
all rows in long_story_article_links for each long_story_id, then deletes all long_stories.

Usage:
  python -m backend.scripts.remove_long_storylines [--dry-run]
"""
import argparse
import logging
from typing import List

from supabase import Client

from backend.storage.supabase_client import get_supabase_client

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)


def get_long_story_ids(supabase: Client) -> List[int]:
    """Return ids of all rows in long_stories."""
    try:
        result = supabase.table("long_stories").select("id").execute()
    except Exception as e:
        if "does not exist" in str(e).lower():
            return []
        raise
    rows = result.data or []
    return [r["id"] for r in rows if r.get("id") is not None]


def run(dry_run: bool = False) -> None:
    supabase = get_supabase_client()
    long_ids = get_long_story_ids(supabase)
    if not long_ids:
        logger.info("No long stories found. Nothing to remove.")
        return

    logger.info("Found %d long story(ies): %s", len(long_ids), long_ids)
    if dry_run:
        logger.info("[DRY RUN] Would delete long_story_article_links for these ids, then delete long_stories rows.")
        return

    for lid in long_ids:
        del_links = supabase.table("long_story_article_links").delete().eq("long_story_id", lid).execute()
        count = len(del_links.data or [])
        logger.info("Deleted %d link(s) for long_story_id=%s", count, lid)
    for lid in long_ids:
        supabase.table("long_stories").delete().eq("id", lid).execute()
        logger.info("Deleted long_story id=%s", lid)

    logger.info("Done. Removed %d long story(ies) and their links.", len(long_ids))


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove all long stories and their article links (long_stories + long_story_article_links).")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be done")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
