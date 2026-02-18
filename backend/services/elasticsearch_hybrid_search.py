"""
Elasticsearch hybrid search (BM25 + kNN) for RAG.
Combines keyword match and vector similarity; used when RAG_USE_ELASTICSEARCH is enabled.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from backend.storage.elasticsearch_indices import (
    NEWS_ARTICLES_INDEX,
    SEC_FILING_CHUNKS_INDEX,
    MACRO_KB_CHUNKS_INDEX,
    LONG_STORIES_INDEX,
)

logger = logging.getLogger(__name__)

# RRF constant for score fusion when doing two separate searches (fallback)
RRF_K = 60


def _rrf_merge(
    hits_by_id: Dict[str, Dict],
    keyword_rank_by_id: Dict[str, int],
    knn_rank_by_id: Dict[str, int],
) -> List[Dict]:
    """Merge two ranked lists by RRF: score = sum(1/(k+rank)). Sort by score desc."""
    for doc_id, rank in keyword_rank_by_id.items():
        if doc_id not in hits_by_id:
            continue
        rrf = 1.0 / (RRF_K + rank)
        hits_by_id[doc_id]["_rrf_score"] = hits_by_id[doc_id].get("_rrf_score", 0) + rrf
    for doc_id, rank in knn_rank_by_id.items():
        if doc_id not in hits_by_id:
            continue
        rrf = 1.0 / (RRF_K + rank)
        hits_by_id[doc_id]["_rrf_score"] = hits_by_id[doc_id].get("_rrf_score", 0) + rrf
    sorted_hits = sorted(
        hits_by_id.values(),
        key=lambda x: x.get("_rrf_score", 0),
        reverse=True,
    )
    for h in sorted_hits:
        h.pop("_rrf_score", None)
    return sorted_hits


def _source_to_article(hit: Dict) -> Dict:
    s = hit.get("_source") or {}
    doc_id = hit.get("_id")
    return {
        "id": s.get("id") or (int(doc_id) if doc_id and str(doc_id).isdigit() else None),
        "ticker": s.get("ticker"),
        "title": s.get("title"),
        "summary": s.get("summary"),
        "url": s.get("url"),
        "published_at": s.get("published_at"),
        "source": s.get("source"),
        "similarity": hit.get("_score") or 0.0,
    }


def search_news_hybrid(
    client,
    query_text: Optional[str],
    query_embedding: List[float],
    tickers: List[str],
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    exclude_article_ids: Optional[Set[int]] = None,
    limit: int = 20,
    max_per_ticker_per_day: Optional[int] = None,
) -> List[Dict]:
    """
    Hybrid search on news_articles: BM25 (title/summary) + kNN (embedding).
    Returns list of article dicts with "similarity" key, same shape as rag_retrieval.retrieve_similar_news.
    """
    if not client or not query_embedding or not tickers:
        return []
    tickers_upper = [t.strip().upper() for t in tickers if t]
    if not tickers_upper:
        return []
    exclude = set(exclude_article_ids or [])
    size = min(limit * 3, 500)
    filter_clauses = [{"terms": {"ticker": tickers_upper}}]
    if start_date:
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        filter_clauses.append({"range": {"published_at": {"gte": start_date.isoformat()}}})
    if end_date:
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        filter_clauses.append({"range": {"published_at": {"lte": end_date.isoformat()}}})
    if exclude:
        filter_clauses.append({"bool": {"must_not": [{"terms": {"id": list(exclude)}}]}})

    must = []
    if query_text and query_text.strip():
        must.append({
            "multi_match": {
                "query": query_text.strip(),
                "fields": ["title^2", "summary"],
                "type": "best_fields",
            },
        })
    if not must:
        must.append({"match_all": {}})

    body = {
        "query": {
            "bool": {
                "must": must,
                "filter": filter_clauses,
            },
        },
        "knn": {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": size,
            "num_candidates": min(size * 2, 500),
            "boost": 0.5,
        },
        "size": size,
        "_source": ["id", "ticker", "title", "summary", "url", "published_at", "source"],
    }
    try:
        resp = client.search(index=NEWS_ARTICLES_INDEX, body=body)
    except Exception as e:
        logger.warning("ES search_news_hybrid failed: %s", e)
        return []
    hits = (resp.get("hits") or {}).get("hits") or []
    out = [_source_to_article(h) for h in hits]
    # Exclude AI-generated sources (match RAG_EXCLUDED_SOURCES behavior)
    from backend.config import RAG_EXCLUDED_SOURCES
    excluded_sources = set(RAG_EXCLUDED_SOURCES or [])
    out = [a for a in out if (a.get("source") or "").strip() not in excluded_sources]
    # Per-(ticker, date) cap
    if max_per_ticker_per_day and max_per_ticker_per_day > 0:
        from backend.pipeline.rag_retrieval import _cap_per_ticker_per_day
        out = _cap_per_ticker_per_day(out, max_per_ticker_per_day)
    return out[:limit]


def search_filing_chunks_hybrid(
    client,
    query_text: Optional[str],
    query_embedding: List[float],
    tickers: List[str],
    limit: int = 20,
    doc_types: Optional[List[str]] = None,
    sections: Optional[List[str]] = None,
    only_most_recent_filing: bool = False,
    filing_ids: Optional[List[int]] = None,
) -> List[Dict]:
    """
    Hybrid search on sec_filing_chunks. Returns list of chunk dicts with similarity, final_score,
    and filing metadata (form_type, filed_date, section, doc_type).
    """
    if not client or not query_embedding or not tickers:
        return []
    tickers_upper = [t.strip().upper() for t in tickers if t]
    if not tickers_upper:
        return []
    filter_clauses = [{"terms": {"ticker": tickers_upper}}]
    if filing_ids and only_most_recent_filing:
        filter_clauses.append({"terms": {"filing_id": filing_ids}})
    if doc_types:
        filter_clauses.append({"terms": {"form_type": [d.strip().upper() for d in doc_types]}})
    if sections:
        filter_clauses.append({"terms": {"section": sections}})

    must = []
    if query_text and query_text.strip():
        must.append({
            "multi_match": {
                "query": query_text.strip(),
                "fields": ["text"],
                "type": "best_fields",
            },
        })
    if not must:
        must.append({"match_all": {}})

    size = min(limit * 2, 100)
    body = {
        "query": {
            "bool": {
                "must": must,
                "filter": filter_clauses,
            },
        },
        "knn": {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": size,
            "num_candidates": min(size * 2, 200),
            "boost": 0.5,
        },
        "size": size,
        "_source": ["id", "filing_id", "ticker", "chunk_index", "text", "section", "doc_type", "filed_date", "form_type"],
    }
    try:
        resp = client.search(index=SEC_FILING_CHUNKS_INDEX, body=body)
    except Exception as e:
        logger.warning("ES search_filing_chunks_hybrid failed: %s", e)
        return []
    hits = (resp.get("hits") or {}).get("hits") or []
    out = []
    for h in hits:
        s = h.get("_source") or {}
        out.append({
            "id": s.get("id"),
            "filing_id": s.get("filing_id"),
            "ticker": s.get("ticker"),
            "chunk_index": s.get("chunk_index"),
            "text": s.get("text"),
            "section": s.get("section"),
            "doc_type": s.get("doc_type"),
            "filed_date": s.get("filed_date"),
            "form_type": s.get("form_type"),
            "similarity": h.get("_score") or 0.0,
            "final_score": h.get("_score") or 0.0,
        })
    return out[:limit]


def search_macro_kb_hybrid(
    client,
    query_text: Optional[str],
    query_embedding: List[float],
    limit: int = 20,
    book_id: Optional[int] = None,
) -> List[Dict]:
    """Hybrid search on macro_kb_chunks. Returns list of chunk dicts (id, book_id, chunk_index, text, score)."""
    if not client or not query_embedding:
        return []
    filter_clauses = []
    if book_id is not None:
        filter_clauses.append({"term": {"book_id": book_id}})
    must = []
    if query_text and query_text.strip():
        must.append({
            "multi_match": {
                "query": query_text.strip(),
                "fields": ["text"],
                "type": "best_fields",
            },
        })
    if not must:
        must.append({"match_all": {}})
    if filter_clauses:
        body_query = {"bool": {"must": must, "filter": filter_clauses}}
    else:
        body_query = {"bool": {"must": must}}

    size = min(limit * 2, 100)
    body = {
        "query": body_query,
        "knn": {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": size,
            "num_candidates": min(size * 2, 200),
            "boost": 0.5,
        },
        "size": size,
        "_source": ["id", "book_id", "chunk_index", "text"],
    }
    try:
        resp = client.search(index=MACRO_KB_CHUNKS_INDEX, body=body)
    except Exception as e:
        logger.warning("ES search_macro_kb_hybrid failed: %s", e)
        return []
    hits = (resp.get("hits") or {}).get("hits") or []
    out = []
    for h in hits:
        s = h.get("_source") or {}
        out.append({
            **s,
            "score": h.get("_score") or 0.0,
        })
    return out[:limit]


def find_similar_long_story_hybrid(
    client,
    ticker: str,
    query_embedding: List[float],
    query_text: Optional[str] = None,
    threshold: float = 0.8,
) -> Optional[Dict]:
    """
    Find the most similar long story for the ticker (embedding + optional BM25).
    Returns single long_story dict (id, ticker, title, canonical_theme, summary) or None.
    """
    if not client or not query_embedding:
        return None
    ticker_upper = (ticker or "").strip().upper()
    if not ticker_upper:
        return None
    must = []
    if query_text and query_text.strip():
        must.append({
            "multi_match": {
                "query": query_text.strip(),
                "fields": ["title^2", "canonical_theme^2", "summary"],
                "type": "best_fields",
            },
        })
    if not must:
        must.append({"match_all": {}})
    body = {
        "query": {
            "bool": {
                "must": must,
                "filter": [{"term": {"ticker": ticker_upper}}],
            },
        },
        "knn": {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": 5,
            "num_candidates": 20,
            "boost": 0.5,
        },
        "size": 1,
        "_source": ["id", "ticker", "title", "canonical_theme", "summary"],
    }
    try:
        resp = client.search(index=LONG_STORIES_INDEX, body=body)
    except Exception as e:
        logger.warning("ES find_similar_long_story_hybrid failed: %s", e)
        return None
    hits = (resp.get("hits") or {}).get("hits") or []
    if not hits:
        return None
    h = hits[0]
    score = h.get("_score") or 0.0
    # ES cosine similarity for dense_vector is often (score+1)/2 in [0,1] or similar; check mapping.
    # Our mapping uses cosine; ES returns _score from similarity. For cosine, score can be in [0,1] or normalized.
    if score < threshold:
        return None
    s = h.get("_source") or {}
    return {
        "id": s.get("id"),
        "ticker": s.get("ticker"),
        "title": s.get("title"),
        "canonical_theme": s.get("canonical_theme"),
        "summary": s.get("summary"),
    }
