"""
RAG Retrieval Module

Handles retrieving similar historical news articles using embedding similarity.
Supports multi-ticker retrieval: primary ticker, tickers mentioned in article text,
and optional related tickers (competitors, suppliers, customers).
After sorting by similarity, applies a per-(ticker, date) cap (max 2 per ticker per day)
for temporal diversity, then returns up to limit articles.
"""
import logging
import json
import ast
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set, Optional, Any, Tuple, Union, Iterable

import numpy as np

from supabase import Client

from backend.config import RAG_RETRIEVAL_LIMIT, RAG_TOP_K_CANDIDATES, RELATED_TICKERS, RAG_EXCLUDED_SOURCES

logger = logging.getLogger(__name__)

# Max articles to keep per (ticker, date) before applying total limit (temporal diversity)
DEFAULT_MAX_PER_TICKER_PER_DAY = 2


def _parse_published_date(published_at: Any) -> Optional[str]:
    """Return date string (YYYY-MM-DD) from published_at for grouping; None if unparseable."""
    if not published_at:
        return None
    try:
        if isinstance(published_at, str):
            if "T" in published_at:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(published_at[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt.date().isoformat()
        if isinstance(published_at, datetime):
            dt = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
            return dt.date().isoformat()
        return None
    except Exception:
        return None


def _cap_per_ticker_per_day(
    articles: List[Dict],
    max_per_ticker_per_day: int,
) -> List[Dict]:
    """
    Keep at most max_per_ticker_per_day articles per (ticker, date), preserving order by similarity.
    Assumes articles are already sorted by similarity descending.
    """
    if not articles or max_per_ticker_per_day < 1:
        return articles
    key_to_articles: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for art in articles:
        ticker = (art.get("ticker") or "").strip().upper() or "UNKNOWN"
        date_key = _parse_published_date(art.get("published_at")) or "unknown"
        key_to_articles[(ticker, date_key)].append(art)
    capped: List[Dict] = []
    for (ticker, date_key), group in key_to_articles.items():
        # Group is already in similarity order if input was; keep top max_per_ticker_per_day
        capped.extend(group[:max_per_ticker_per_day])
    # Sort by similarity desc, then by published_at asc for tie-break (temporal diversity)
    def _sort_key(a: Dict) -> Tuple[float, str]:
        sim = a.get("similarity", 0.0)
        pub = a.get("published_at") or ""
        date_part = pub[:10] if isinstance(pub, str) and len(pub) >= 10 else "9999-99-99"
        return (-sim, date_part)
    capped.sort(key=_sort_key)
    if len(capped) < len(articles):
        logger.debug(
            "RAG cap: kept %s of %s (max %s per ticker per day)",
            len(capped),
            len(articles),
            max_per_ticker_per_day,
        )
    return capped


def extract_tickers_from_article(text: str, valid_tickers: Set[str]) -> Set[str]:
    """
    Extract ticker symbols mentioned in article text (title + summary).
    Prefers parenthetical pattern (TICKER); optionally matches known tickers by word boundary.

    Args:
        text: Article title + summary (or combined text).
        valid_tickers: Set of tickers that exist in the stocks table.

    Returns:
        Set of tickers found in text and present in valid_tickers.
    """
    if not text or not valid_tickers:
        return set()
    text = (text or "").strip()
    valid_upper = {t.upper() for t in valid_tickers}
    found: Set[str] = set()

    # Prefer pattern (TICKER) e.g. (AAPL), (MSFT)
    for m in re.finditer(r"\(([A-Za-z]{2,5})\)", text):
        ticker = m.group(1).upper()
        if ticker in valid_upper:
            found.add(ticker)

    # Word-boundary match for known tickers (2-5 chars to avoid false positives like "A", "IT")
    for ticker in valid_upper:
        if len(ticker) < 2 or len(ticker) > 5:
            continue
        if re.search(r"\b" + re.escape(ticker) + r"\b", text, re.IGNORECASE):
            found.add(ticker)

    return found


def get_related_tickers(primary_ticker: str, supabase: Optional[Client] = None) -> List[str]:
    """
    Return related tickers (competitors, suppliers, customers) for the primary ticker.
    Prefers stocks.related_tickers from DB when supabase is provided; else uses config RELATED_TICKERS.

    Args:
        primary_ticker: Stock ticker symbol.
        supabase: Optional Supabase client; if provided, reads stocks.related_tickers from DB.

    Returns:
        List of related ticker symbols.
    """
    if supabase:
        try:
            result = supabase.table("stocks").select("related_tickers").eq("ticker", primary_ticker.upper()).limit(1).execute()
            if result.data and len(result.data) > 0:
                raw = result.data[0].get("related_tickers")
                if isinstance(raw, list) and raw:
                    return [str(t).strip().upper() for t in raw if t]
        except Exception as e:
            logger.debug(f"Could not read stocks.related_tickers for {primary_ticker}: {e}")
    return list(RELATED_TICKERS.get(primary_ticker.upper(), []))


def _parse_embedding(embedding) -> np.ndarray:
    """Parse embedding from various formats (list, string representation, etc.)."""
    if embedding is None:
        return None
    if isinstance(embedding, list):
        return np.array(embedding, dtype=float)
    if isinstance(embedding, str):
        try:
            parsed = json.loads(embedding)
            return np.array(parsed, dtype=float)
        except (json.JSONDecodeError, ValueError):
            try:
                parsed = ast.literal_eval(embedding)
                return np.array(parsed, dtype=float)
            except (ValueError, SyntaxError):
                logger.warning(f"Could not parse embedding string: {embedding[:100]}...")
                return None
    if isinstance(embedding, np.ndarray):
        return embedding.astype(float)
    return None


def _fetch_and_score_for_ticker(
    supabase: Client,
    ticker: str,
    new_embedding: np.ndarray,
    new_norm: float,
    exclude_article_ids: Set[int],
    fetch_limit: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[Dict]:
    """
    Fetch articles for one ticker and compute cosine similarity.
    Optionally restrict to start_date <= published_at <= end_date (for short vs long window).
    Excludes articles whose id is in exclude_article_ids.
    Returns list of article dicts with "similarity" key (no global sort or limit).
    """
    try:
        query = (
            supabase.table("news_articles")
            .select("id, ticker, title, summary, url, published_at, embedding, source")
            .eq("ticker", ticker.upper())
            .not_.is_("embedding", "null")
        )
        if exclude_article_ids:
            query = query.not_.in_("id", list(exclude_article_ids))
        if start_date is not None:
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            query = query.gte("published_at", start_date.isoformat())
        if end_date is not None:
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            query = query.lte("published_at", end_date.isoformat())
        result = query.order("published_at", desc=True).limit(fetch_limit).execute()

        articles = result.data if result.data else []
        if not articles:
            return []
        # Exclude AI-generated sources (Gemini Generated, OpenAI Generated) from RAG similar-article retrieval
        excluded = set(RAG_EXCLUDED_SOURCES or [])
        articles = [a for a in articles if (a.get("source") or "").strip() not in excluded]

        out = []
        for article in articles:
            if not article.get("embedding"):
                continue
            old_embedding = _parse_embedding(article["embedding"])
            if old_embedding is None:
                continue
            old_norm = np.linalg.norm(old_embedding)
            if old_norm <= 0:
                continue
            similarity = float(np.dot(new_embedding, old_embedding) / (new_norm * old_norm))
            article = dict(article)
            article["similarity"] = similarity
            out.append(article)
        return out
    except Exception as e:
        logger.debug(f"Error fetching similar news for ticker {ticker}: {e}")
        return []


def _normalize_exclude_ids(
    exclude_article_ids: Optional[Union[int, Iterable[int]]],
) -> Set[int]:
    """Normalize exclude_article_ids to a set of ints. None or empty → set()."""
    if exclude_article_ids is None:
        return set()
    if isinstance(exclude_article_ids, int):
        return {exclude_article_ids}
    return set(int(x) for x in exclude_article_ids)


async def retrieve_similar_news(
    supabase: Client,
    tickers: List[str],
    new_article_embedding: List[float],
    exclude_article_ids: Optional[Union[int, Iterable[int]]] = None,
    limit: int = RAG_RETRIEVAL_LIMIT,
    max_per_ticker_per_day: int = DEFAULT_MAX_PER_TICKER_PER_DAY,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    query_text: Optional[str] = None,
) -> List[Dict]:
    """
    Retrieve similar historical news articles using embedding similarity
    across multiple tickers (primary, mentioned in article, related).
    Optionally restrict to start_date <= published_at <= end_date (e.g. last 7 days for short,
    last 12 months for long storyline). After sorting by similarity, caps at max_per_ticker_per_day
    per (ticker, date) for temporal diversity, then returns up to limit articles.

    Args:
        supabase: Supabase client instance
        tickers: Ordered list of tickers to query (primary first). Deduplicated.
        new_article_embedding: Embedding vector of the query (e.g. new article or story).
        exclude_article_ids: Article ID(s) to exclude from results (single int or iterable of ints).
        limit: Maximum number of similar articles to return (global top N)
        max_per_ticker_per_day: Max articles per (ticker, date) before applying limit. Default 2.
        start_date: Optional; only articles with published_at >= start_date.
        end_date: Optional; only articles with published_at <= end_date.
        query_text: Optional text for hybrid search (BM25); used when Elasticsearch is enabled.

    Returns:
        List of article dicts with similarity scores, ordered by similarity
    """
    if not new_article_embedding:
        logger.warning("No embedding provided for similar-news retrieval, skipping")
        return []

    exclude_set = _normalize_exclude_ids(exclude_article_ids)

    # Deduplicate tickers while preserving order (primary first)
    seen: Set[str] = set()
    tickers_ordered: List[str] = []
    for t in tickers:
        u = (t or "").strip().upper()
        if u and u not in seen:
            seen.add(u)
            tickers_ordered.append(u)

    if not tickers_ordered:
        logger.warning("No tickers to query for similar news")
        return []

    logger.debug(f"Retrieving similar articles for tickers: {tickers_ordered} (limit={limit}, exclude={len(exclude_set)} ids)")

    try:
        new_embedding = _parse_embedding(new_article_embedding)
        if new_embedding is None:
            logger.warning("Could not parse new article embedding, skipping retrieval")
            return []
        new_norm = np.linalg.norm(new_embedding)
        if new_norm == 0:
            logger.warning("New article embedding has zero norm, skipping similarity search")
            return []

        # Elasticsearch hybrid path (when enabled)
        from backend.config import RAG_USE_ELASTICSEARCH
        from backend.storage.elasticsearch_client import get_elasticsearch_client
        from backend.services.elasticsearch_hybrid_search import search_news_hybrid
        if RAG_USE_ELASTICSEARCH:
            es_client = get_elasticsearch_client()
            if es_client is not None:
                embedding_list = new_article_embedding if isinstance(new_article_embedding, list) else new_embedding.tolist()
                articles = search_news_hybrid(
                    es_client,
                    query_text=query_text,
                    query_embedding=embedding_list,
                    tickers=tickers_ordered,
                    start_date=start_date,
                    end_date=end_date,
                    exclude_article_ids=exclude_set,
                    limit=limit,
                    max_per_ticker_per_day=max_per_ticker_per_day,
                )
                if articles is not None:
                    return articles

        # Per-ticker fetch size: enough candidates after merge (plan: limit * 2 or * 3 per ticker)
        fetch_limit = max(limit * 2, limit * 3)

        merged: Dict[int, Dict] = {}
        for ticker in tickers_ordered:
            batch = _fetch_and_score_for_ticker(
                supabase,
                ticker,
                new_embedding,
                new_norm,
                exclude_set,
                fetch_limit,
                start_date=start_date,
                end_date=end_date,
            )
            for article in batch:
                aid = article.get("id")
                if aid is None:
                    continue
                sim = article.get("similarity", 0.0)
                if aid not in merged or merged[aid].get("similarity", 0) < sim:
                    merged[aid] = article

        # Sort by similarity descending
        sorted_by_sim = sorted(
            merged.values(),
            key=lambda x: x.get("similarity", 0),
            reverse=True,
        )
        # Cap per (ticker, date) for temporal diversity, then apply total limit
        capped = _cap_per_ticker_per_day(sorted_by_sim, max_per_ticker_per_day)
        top_articles = capped[:limit]
        top_sim = top_articles[0].get("similarity", 0) if top_articles else 0
        logger.debug(f"Found {len(top_articles)} similar articles (top similarity: {top_sim:.3f})")
        return top_articles

    except Exception as e:
        logger.error(f"Error retrieving similar news: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []
