"""
Clean up long_stories that have no linked articles (orphans).

Usage:
  python -m backend.scripts.cleanup_orphan_storylines [--dry-run]
"""
import argparse
import logging
from typing import List, Set

from supabase import Client

from backend.storage.supabase_client import get_supabase_client

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)

PAGE_SIZE = 1000


def get_long_story_ids_with_links(supabase: Client) -> Set[int]:
    """Return set of long_story_id that have at least one row in long_story_article_links."""
    linked: Set[int] = set()
    offset = 0
    while True:
        try:
            result = (
                supabase.table("long_story_article_links")
                .select("long_story_id")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
        except Exception as e:
            if "does not exist" in str(e).lower():
                return linked
            logger.error("Failed to fetch long_story_article_links: %s", e)
            raise
        rows = result.data or []
        for r in rows:
            lid = r.get("long_story_id")
            if lid is not None:
                try:
                    linked.add(int(lid))
                except (TypeError, ValueError):
                    pass
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return linked


def find_orphan_long_stories(supabase: Client) -> List[int]:
    """Return list of long_stories.id that have no rows in long_story_article_links."""
    try:
        result = supabase.table("long_stories").select("id").execute()
    except Exception as e:
        if "does not exist" in str(e).lower():
            return []
        raise
    all_ids = [r["id"] for r in (result.data or []) if r.get("id") is not None]
    linked = get_long_story_ids_with_links(supabase)
    return [lid for lid in all_ids if lid not in linked]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete long_stories that have no linked articles."
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be done")
    args = parser.parse_args()

    supabase = get_supabase_client()
    orphan_long = find_orphan_long_stories(supabase)
    if not orphan_long:
        logger.info("No orphan long_stories (every long story has at least one linked article). Nothing to do.")
        return
    logger.info("Found %d orphan long_story(ies) with no linked articles: %s", len(orphan_long), orphan_long)
    if args.dry_run:
        logger.info("[DRY RUN] Would delete these rows from long_stories.")
        return
    for lid in orphan_long:
        supabase.table("long_stories").delete().eq("id", lid).execute()
        logger.info("Deleted orphan long_story id=%s", lid)
    logger.info("Done. Deleted %d orphan long_story(ies).", len(orphan_long))


if __name__ == "__main__":
    main()
