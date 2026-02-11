"""
Collect macro raw items from Alpha Vantage, dedupe, route (rule-based), write to macro_raw_items.
Optionally keep writing to macro_articles for backward compatibility (handled by pipeline).
"""
import asyncio
import logging
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

import httpx

from backend.config import ALPHA_VANTAGE_API_KEY
from backend.storage.macro_raw_items_save import save_raw_items
from backend.storage.supabase_client import get_supabase_client

from backend.macro.router import route_raw_items

logger = logging.getLogger(__name__)

# Reuse Alpha Vantage topic names and fetch from macro_articles_main
from backend.storage import macro_articles_main

AV_TOPICS = macro_articles_main.MACRO_TOPICS  # economy_fiscal, economy_monetary, economy_macro
fetch_macro_news_by_topic = macro_articles_main.fetch_macro_news_by_topic
_deduplicate_similar_articles = macro_articles_main._deduplicate_similar_articles


def _article_to_raw_item(article: Dict[str, Any], as_of_date: date) -> Dict[str, Any]:
    """Convert Alpha Vantage article to raw item shape for macro_raw_items."""
    published_at = article.get("published_at")
    pub_iso = published_at.isoformat() if hasattr(published_at, "isoformat") else (published_at or "")
    return {
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "url": article.get("url", ""),
        "source": article.get("source", "Alpha Vantage"),
        "published_at": published_at,
        "collector": "alpha_vantage",
        "topic_candidate": article.get("primary_topic"),
        "topic": None,  # filled by router
        "relevance_score": None,  # filled by router
        "region": None,
    }


async def fetch_raw_for_date(
    as_of_date: date,
    api_key: Optional[str] = None,
    limit_per_topic: int = 1000,
    delay_between_calls: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Fetch macro news from Alpha Vantage for the given date; return raw items (no topic/relevance yet).
    """
    if api_key is None:
        api_key = ALPHA_VANTAGE_API_KEY
    if not api_key:
        logger.warning("ALPHA_VANTAGE_API_KEY not set; skipping fetch")
        return []
    start = datetime(as_of_date.year, as_of_date.month, as_of_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    seen_urls: Set[str] = set()
    seen_titles: Set[tuple] = set()
    all_raw: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, topic in enumerate(AV_TOPICS):
            logger.info("Fetching raw topic %d/%d: %s", i + 1, len(AV_TOPICS), topic)
            try:
                articles = await fetch_macro_news_by_topic(
                    client=client,
                    topic=topic,
                    time_from=start,
                    time_to=end,
                    api_key=api_key,
                    limit=limit_per_topic,
                )
                for article in articles:
                    url = article.get("url", "")
                    title = article.get("title", "")
                    published_at = article.get("published_at")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    else:
                        title_key = (title, published_at.isoformat() if hasattr(published_at, "isoformat") else "")
                        if title_key in seen_titles:
                            continue
                        seen_titles.add(title_key)
                    raw = _article_to_raw_item(article, as_of_date)
                    raw["primary_topic"] = macro_articles_main._get_primary_topic(article)
                    all_raw.append(raw)
            except Exception as e:
                logger.error("Error fetching macro raw for topic %s: %s", topic, e)
            else:
                logger.info("Topic %s: %d articles (total so far: %d)", topic, len(articles), len(all_raw))
            if i < len(AV_TOPICS) - 1:
                await asyncio.sleep(delay_between_calls)
    logger.info("Fetch complete: %d raw items before dedupe", len(all_raw))
    return all_raw


def collect_and_save_raw(
    as_of_date: date,
    supabase=None,
    dedupe_similar: bool = True,
    similarity_threshold: float = 0.85,
) -> int:
    """
    Fetch macro news for as_of_date, dedupe, route (rule-based), save to macro_raw_items.
    Returns count of raw items saved.
    """
    if supabase is None:
        supabase = get_supabase_client()
    raw_list = asyncio.run(fetch_raw_for_date(as_of_date))
    if not raw_list:
        logger.info("No macro raw items for %s", as_of_date)
        return 0
    logger.info("Collected %d raw items; deduping (similarity=%.2f)...", len(raw_list), similarity_threshold)
    if dedupe_similar:
        # _deduplicate_similar_articles expects list of article dicts with title/summary
        raw_list = _deduplicate_similar_articles(raw_list, similarity_threshold=similarity_threshold)
        logger.info("After dedupe: %d items", len(raw_list))
    logger.info("Routing topics (rule-based)...")
    routed = route_raw_items(raw_list)
    n = save_raw_items(supabase, routed, as_of_date, collector="alpha_vantage")
    logger.info("Saved %d items to macro_raw_items", n)
    return n
