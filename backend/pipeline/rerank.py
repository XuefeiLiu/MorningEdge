"""
Rerank module: LM-based cross-encoder reranking (local, free).

Retrieval returns top-K candidates; this module reranks them by relevance to the query
and returns the top N. Uses sentence-transformers CrossEncoder so there is no API cost.
For long-story (history) mode, use select_top_sorted_by_date for top N by score with a per-month cap
so the selection spans several months (default max 4 per month). select_best_per_month remains for one-article-per-month if needed.
"""
import logging
from collections import defaultdict
from typing import List, Dict, Any, Optional

from backend.config import RERANK_MODEL, RAG_RERANK_TOP_N_RECENT_MIN, RAG_RERANK_TOP_N_RECENT_MAX, RAG_RERANK_TOP_N_HISTORY

logger = logging.getLogger(__name__)

# Lazy-loaded cross-encoder model (avoids loading at import time)
_cross_encoder = None


def _get_model():
    """Load the cross-encoder model once (lazy)."""
    global _cross_encoder
    if _cross_encoder is None:
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = CrossEncoder(RERANK_MODEL)
            logger.info(f"Loaded rerank model: {RERANK_MODEL}")
        except Exception as e:
            logger.error(f"Failed to load rerank model {RERANK_MODEL}: {e}")
            raise
    return _cross_encoder


def _candidate_text(c: Dict) -> str:
    """Build a single text from candidate title and summary for scoring."""
    title = (c.get("title") or "").strip()
    summary = (c.get("summary") or "").strip()
    if title and summary:
        return f"{title}\n{summary}"
    return title or summary or ""


def rerank(
    query_text: str,
    candidates: List[Dict],
    top_n: int,
    query_embedding: Optional[List[float]] = None,
) -> List[Dict]:
    """
    Rerank candidates by relevance to the query using a local cross-encoder.

    Args:
        query_text: Query string (e.g. article title+summary or user question).
        candidates: List of candidate dicts with at least "title" and optionally "summary".
        top_n: Number of top candidates to return after reranking.
        query_embedding: Optional; ignored for cross-encoder (kept for interface consistency).

    Returns:
        List of top_n candidates, each with an added "rerank_score" key, sorted by score descending.
    """
    if not query_text or not candidates:
        return candidates[:top_n] if candidates else []

    query_text = (query_text or "").strip()
    if not query_text:
        return candidates[:top_n]

    try:
        model = _get_model()
    except Exception:
        logger.warning("Rerank model unavailable; returning candidates unchanged (no reranking)")
        return candidates[:top_n]

    pairs = [(query_text, _candidate_text(c)) for c in candidates]
    try:
        scores = model.predict(pairs)
    except Exception as e:
        logger.warning(f"Rerank predict failed: {e}; returning candidates unchanged")
        return candidates[:top_n]

    # scores can be a list or numpy array; ensure list of float
    if hasattr(scores, "tolist"):
        scores = scores.tolist()
    scores = list(scores)

    out = []
    for i, c in enumerate(candidates):
        score = float(scores[i]) if i < len(scores) else 0.0
        out.append({**dict(c), "rerank_score": score})
    out.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
    return out[:top_n]


def rerank_top_n_recent() -> int:
    """Default N for recent (short) mode: use midpoint of configured range."""
    return max(RAG_RERANK_TOP_N_RECENT_MIN, (RAG_RERANK_TOP_N_RECENT_MIN + RAG_RERANK_TOP_N_RECENT_MAX) // 2)


def rerank_top_n_history() -> int:
    """N for history (long) mode."""
    return RAG_RERANK_TOP_N_HISTORY


def _month_key(published_at: Any) -> Optional[str]:
    """Return YYYY-MM from published_at for grouping; None if unparseable."""
    if published_at is None:
        return None
    try:
        s = published_at
        if hasattr(s, "isoformat"):
            s = s.isoformat()
        s = str(s).strip()
        if len(s) >= 7 and s[4] == "-":
            return s[:7]  # YYYY-MM
        return None
    except Exception:
        return None


def select_best_per_month(
    candidates: List[Dict],
    max_articles: int = 12,
    score_key: str = "rerank_score",
    fallback_score_key: str = "similarity",
) -> List[Dict]:
    """
    Select at most one article per month (from candidates spanning past several years) for long-story temporal diversity.
    For each month, keeps the candidate with the highest score (rerank_score or similarity).
    Result is sorted by published_at ascending (chronological narrative).

    Args:
        candidates: Reranked candidates with published_at and score_key (or fallback_score_key).
        max_articles: Maximum number of articles to return (default 12, one per month).
        score_key: Key for relevance score (default "rerank_score").
        fallback_score_key: Fallback key if score_key missing (default "similarity").

    Returns:
        List of up to max_articles candidates, one per month, sorted by published_at ascending.
    """
    if not candidates:
        return []
    by_month: Dict[str, List[Dict]] = defaultdict(list)
    for c in candidates:
        month = _month_key(c.get("published_at"))
        if month is None:
            continue
        by_month[month].append(c)
    # Best per month: highest score
    def score(a: Dict) -> float:
        return float(a.get(score_key) or a.get(fallback_score_key) or 0.0)

    best_per_month: List[Dict] = []
    for month, group in sorted(by_month.items(), reverse=True):  # recent months first when picking
        best = max(group, key=score)
        best_per_month.append(best)
    # Sort by published_at ascending (chronological for narrative)
    def pub_ts(a: Dict) -> str:
        p = a.get("published_at") or ""
        return p[:19] if isinstance(p, str) and len(p) >= 19 else str(p)

    best_per_month.sort(key=pub_ts)
    return best_per_month[:max_articles]


def select_top_sorted_by_date(
    candidates: List[Dict],
    max_articles: int = 12,
    max_per_month: int = 4,
    score_key: str = "rerank_score",
    fallback_score_key: str = "similarity",
) -> List[Dict]:
    """
    Select up to max_articles by rerank score, with a per-month cap so the result spans several months.
    Caps each month at max_per_month articles; fills in score-desc order. Result sorted by published_at ascending.
    """
    if not candidates:
        return []

    def score(a: Dict) -> float:
        return float(a.get(score_key) or a.get(fallback_score_key) or 0.0)

    # Sort by score descending so we pick best first
    by_score = sorted(candidates, key=score, reverse=True)
    selected: List[Dict] = []
    count_per_month: Dict[str, int] = defaultdict(int)

    for c in by_score:
        if len(selected) >= max_articles:
            break
        month = _month_key(c.get("published_at"))
        if month is None:
            selected.append(c)
            continue
        if count_per_month[month] < max_per_month:
            selected.append(c)
            count_per_month[month] += 1

    def pub_ts(a: Dict) -> str:
        p = a.get("published_at") or ""
        return p[:19] if isinstance(p, str) and len(p) >= 19 else str(p)

    selected.sort(key=pub_ts)
    return selected
