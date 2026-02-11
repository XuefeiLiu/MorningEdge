"""
Remove duplicate news_articles: same title on the same day (per ticker).

Duplicates are (ticker, normalized title, calendar day): we keep one row (smallest id)
and delete the rest. Before deleting articles we delete their links in long_story_article_links.

Usage:
  python -m backend.scripts.remove_duplicate_news_articles [--dry-run] [--batch-size 1000]
"""
import argparse
import logging
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from supabase import Client

from backend.storage.supabase_client import get_supabase_client

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 1000


def _date_key(published_at: Any) -> str:
    """Return YYYY-MM-DD from published_at; empty string if unparseable."""
    if not published_at:
        return ""
    try:
        s = published_at
        if hasattr(s, "isoformat"):
            s = s.isoformat()
        s = str(s).strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
        return ""
    except Exception:
        return ""


def _normalize_title(title: str) -> str:
    return (title or "").strip()


def fetch_all_articles(supabase: Client, batch_size: int = DEFAULT_BATCH_SIZE) -> List[Dict]:
    """Fetch id, ticker, title, published_at for all news_articles (paginated)."""
    rows: List[Dict] = []
    offset = 0
    while True:
        result = (
            supabase.table("news_articles")
            .select("id, ticker, title, published_at")
            .order("id", desc=False)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        data = result.data or []
        rows.extend(data)
        if len(data) < batch_size:
            break
        offset += batch_size
        logger.info("Fetched %d articles so far...", len(rows))
    return rows


def find_duplicate_ids(articles: List[Dict]) -> List[int]:
    """
    Group by (ticker, normalized title, date). For each group with more than one,
    keep the one with smallest id and return the rest as duplicate ids.
    """
    key_to_rows: Dict[Tuple[str, str, str], List[Dict]] = defaultdict(list)
    for r in articles:
        ticker = (r.get("ticker") or "").strip().upper()
        title = _normalize_title(r.get("title") or "")
        date = _date_key(r.get("published_at"))
        if not date:
            continue
        key_to_rows[(ticker, title, date)].append(r)

    duplicate_ids: List[int] = []
    for (_ticker, _title, _date), group in key_to_rows.items():
        if len(group) <= 1:
            continue
        group_sorted = sorted(group, key=lambda x: x.get("id") or 0)
        for r in group_sorted[1:]:
            aid = r.get("id")
            if aid is not None:
                duplicate_ids.append(aid)
    return duplicate_ids


def run(dry_run: bool = False, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
    supabase = get_supabase_client()
    logger.info("Fetching all news_articles (id, ticker, title, published_at)...")
    articles = fetch_all_articles(supabase, batch_size=batch_size)
    if not articles:
        logger.info("No articles found. Nothing to do.")
        return

    logger.info("Found %d total articles. Detecting duplicates (same ticker + title + day)...", len(articles))
    duplicate_ids = find_duplicate_ids(articles)
    if not duplicate_ids:
        logger.info("No duplicate articles (same title on same day). Nothing to remove.")
        return

    logger.info("Found %d duplicate article(s) to remove: %s", len(duplicate_ids), duplicate_ids[:20])
    if len(duplicate_ids) > 20:
        logger.info("... and %d more", len(duplicate_ids) - 20)
    if dry_run:
        logger.info("[DRY RUN] Would delete their links in long_story_article_links, then delete these rows in news_articles.")
        return

    # Delete links first (long_story_article_links references article_id)
    for aid in duplicate_ids:
        try:
            supabase.table("long_story_article_links").delete().eq("article_id", aid).execute()
            logger.debug("Deleted links for article_id=%s", aid)
        except Exception as e:
            logger.warning("Could not delete links for article_id=%s: %s", aid, e)

    # Delete duplicate articles
    for aid in duplicate_ids:
        try:
            supabase.table("news_articles").delete().eq("id", aid).execute()
            logger.info("Deleted duplicate article id=%s", aid)
        except Exception as e:
            logger.error("Failed to delete article id=%s: %s", aid, e)

    logger.info("Done. Removed %d duplicate news_articles (same title on same day).", len(duplicate_ids))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove duplicate news_articles (same ticker + title on same day) and their storyline links."
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be done")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Fetch batch size for reading articles (default %d)" % DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    run(dry_run=args.dry_run, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
