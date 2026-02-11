"""
Remove long stories whose linked articles are all from the same week, or that have no linked articles.

Long stories live in long_stories; links in long_story_article_links. Long stories should span
multiple weeks. Removes:
- Long stories with no linked articles (orphans).
- Long stories where all linked articles fall in a single ISO week.

Usage:
  python -m backend.scripts.remove_long_storylines_same_week [--dry-run]
"""
import argparse
import logging
from datetime import datetime, timezone
from typing import List, Optional, Set, Tuple

from supabase import Client

from backend.storage.supabase_client import get_supabase_client

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)


def _week_key(published_at) -> Optional[Tuple[int, int]]:
    """Return (iso_year, iso_week) for published_at, or None if unparseable."""
    if published_at is None:
        return None
    try:
        dt = (
            datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            if isinstance(published_at, str)
            else published_at
        )
        if hasattr(dt, "tzinfo") and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        y, w, _ = dt.isocalendar()
        return (y, w)
    except (TypeError, ValueError, AttributeError):
        return None


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


def get_linked_article_dates(supabase: Client, long_story_id: int) -> List[str]:
    """Return list of published_at (ISO strings) for articles linked to this long story."""
    link_result = (
        supabase.table("long_story_article_links")
        .select("article_id")
        .eq("long_story_id", long_story_id)
        .execute()
    )
    link_data = link_result.data or []
    article_ids = list({int(r["article_id"]) for r in link_data if r.get("article_id") is not None})
    if not article_ids:
        return []
    art_result = (
        supabase.table("news_articles")
        .select("published_at")
        .in_("id", article_ids)
        .execute()
    )
    art_data = art_result.data or []
    return [a.get("published_at") for a in art_data if a.get("published_at") is not None]


def all_same_week(published_dates: List[str]) -> bool:
    """Return True if all published_dates fall in the same ISO week (or empty)."""
    weeks: Set[Tuple[int, int]] = set()
    for pub in published_dates:
        wk = _week_key(pub)
        if wk is not None:
            weeks.add(wk)
    return len(weeks) <= 1


def run(dry_run: bool = False) -> None:
    supabase = get_supabase_client()
    long_ids = get_long_story_ids(supabase)
    if not long_ids:
        logger.info("No long stories found.")
        return

    to_remove: List[int] = []
    for lid in long_ids:
        dates = get_linked_article_dates(supabase, lid)
        if not dates:
            to_remove.append(lid)
            logger.info("Long story id=%s: no linked articles -> will remove", lid)
        elif all_same_week(dates):
            to_remove.append(lid)
            logger.info("Long story id=%s: all %d linked article(s) from same week -> will remove", lid, len(dates))

    if not to_remove:
        logger.info("No long stories to remove (none with same-week-only or no linked articles).")
        return

    logger.info("Found %d long story(ies) to remove (same-week or no links): %s", len(to_remove), to_remove)
    if dry_run:
        logger.info("[DRY RUN] Would delete long_story_article_links for these ids, then delete long_stories rows.")
        return

    for lid in to_remove:
        del_links = supabase.table("long_story_article_links").delete().eq("long_story_id", lid).execute()
        logger.info("Deleted %d link(s) for long_story_id=%s", len(del_links.data or []), lid)
    for lid in to_remove:
        supabase.table("long_stories").delete().eq("id", lid).execute()
        logger.info("Deleted long story id=%s", lid)

    logger.info("Done. Removed %d long story(ies) (same-week or no linked articles).", len(to_remove))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove long stories (long_stories) whose linked articles are all from the same week or have no links."
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be done")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
