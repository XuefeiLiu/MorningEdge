"""
Anchor source: Gemini-sourced rows in news_articles (Source-LLM brief).
Each such row is one anchor seed: article_id, title, summary for embedding and assignment.
"""
import logging
from datetime import date, datetime, timezone, timedelta
from typing import List, Optional

from supabase import Client

from backend.storage.news_articles_query import get_articles
from backend.config import GEMINI_GENERATED_SOURCE

logger = logging.getLogger(__name__)


def _is_gemini_article(row: dict) -> bool:
    """True if article is from Gemini (Source-LLM brief)."""
    collector = (row.get("collector") or "").strip().lower()
    source = (row.get("source") or "").strip()
    return collector == "gemini" or source == GEMINI_GENERATED_SOURCE


def get_anchor_seeds(
    supabase: Client,
    asof_date: date,
    tickers: Optional[List[str]] = None,
) -> List[dict]:
    """
    Query news_articles for the given date and return only Gemini-sourced rows as anchor seeds.
    Each anchor = { "article_id", "ticker", "title", "summary", "published_at" } for embedding and linking.

    Args:
        supabase: Supabase client
        asof_date: Date to fetch articles for (day in ET)
        tickers: Optional list of tickers to restrict to; if None, all tickers for the day

    Returns:
        List of anchor dicts with article_id, ticker, title, summary, published_at
    """
    start = datetime(asof_date.year, asof_date.month, asof_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    articles = get_articles(supabase, ticker=None, start_date=start, end_date=end, limit=5000)
    if tickers:
        ticker_set = {t.strip().upper() for t in tickers}
        articles = [a for a in articles if (a.get("ticker") or "").strip().upper() in ticker_set]

    anchors = []
    for row in articles:
        if not _is_gemini_article(row):
            continue
        article_id = row.get("id")
        if article_id is None:
            continue
        anchors.append({
            "article_id": int(article_id),
            "ticker": (row.get("ticker") or "").strip() or None,
            "title": (row.get("title") or "").strip(),
            "summary": (row.get("summary") or "").strip(),
            "published_at": row.get("published_at"),
        })
    logger.info("Anchor seeds: %d Gemini-sourced articles for asof_date=%s", len(anchors), asof_date)
    return anchors
