"""
Optional sync of RAG data from Supabase to Elasticsearch (when RAG_USE_ELASTICSEARCH).
Non-blocking: log and skip on failure. Used on write paths and by backfill script.
"""
import logging
from typing import Any, Dict, List, Optional

from backend.config import RAG_USE_ELASTICSEARCH
from backend.storage.elasticsearch_client import get_elasticsearch_client
from backend.storage.embedding_utils import parse_embedding_from_db
from backend.storage.elasticsearch_indices import (
    NEWS_ARTICLES_INDEX,
    SEC_FILING_CHUNKS_INDEX,
    MACRO_KB_CHUNKS_INDEX,
    LONG_STORIES_INDEX,
)

logger = logging.getLogger(__name__)


def _doc_id(doc: Dict[str, Any], key: str = "id") -> Optional[str]:
    val = doc.get(key)
    return str(val) if val is not None else None


def _ticker_str(val: Any) -> str:
    """Normalize ticker to string for ES (Supabase may return str or other)."""
    if val is None:
        return ""
    return str(val).strip().upper()


def index_news_article(doc: Dict[str, Any]) -> None:
    """Index one news_articles row into ES. No-op if ES disabled or client unavailable."""
    if not RAG_USE_ELASTICSEARCH:
        return
    client = get_elasticsearch_client()
    if client is None:
        return
    doc_id = _doc_id(doc)
    if not doc_id:
        return
    embedding = parse_embedding_from_db(doc.get("embedding"))
    if embedding is None:
        return
    es_doc = {
        "id": doc.get("id"),
        "ticker": _ticker_str(doc.get("ticker")),
        "title": doc.get("title") or "",
        "summary": doc.get("summary") or "",
        "url": doc.get("url") or "",
        "published_at": doc.get("published_at"),
        "source": doc.get("source") or "",
        "embedding": embedding,
    }
    try:
        client.index(index=NEWS_ARTICLES_INDEX, id=doc_id, document=es_doc)
    except Exception as e:
        logger.debug("ES index news_article %s: %s", doc_id, e)


def index_filing_chunk(doc: Dict[str, Any]) -> None:
    """Index one sec_filing_chunks row. Optional filed_date, form_type from join."""
    if not RAG_USE_ELASTICSEARCH:
        return
    client = get_elasticsearch_client()
    if client is None:
        return
    doc_id = _doc_id(doc)
    embedding = parse_embedding_from_db(doc.get("embedding"))
    if not doc_id or embedding is None:
        return
    es_doc = {
        "id": doc.get("id"),
        "filing_id": doc.get("filing_id"),
        "ticker": _ticker_str(doc.get("ticker")),
        "chunk_index": doc.get("chunk_index", 0),
        "text": doc.get("text") or "",
        "section": doc.get("section"),
        "doc_type": doc.get("doc_type"),
        "filed_date": doc.get("filed_date"),
        "form_type": doc.get("form_type"),
        "embedding": embedding,
    }
    try:
        client.index(index=SEC_FILING_CHUNKS_INDEX, id=doc_id, document=es_doc)
    except Exception as e:
        logger.debug("ES index filing_chunk %s: %s", doc_id, e)


def index_macro_kb_chunk(doc: Dict[str, Any]) -> None:
    """Index one macro_kb_chunks row."""
    if not RAG_USE_ELASTICSEARCH:
        return
    client = get_elasticsearch_client()
    if client is None:
        return
    doc_id = _doc_id(doc)
    embedding = parse_embedding_from_db(doc.get("embedding"))
    if not doc_id or embedding is None:
        return
    es_doc = {
        "id": doc.get("id"),
        "book_id": doc.get("book_id"),
        "chunk_index": doc.get("chunk_index", 0),
        "text": doc.get("text") or "",
        "embedding": embedding,
    }
    try:
        client.index(index=MACRO_KB_CHUNKS_INDEX, id=doc_id, document=es_doc)
    except Exception as e:
        logger.debug("ES index macro_kb_chunk %s: %s", doc_id, e)


def index_long_story(doc: Dict[str, Any]) -> None:
    """Index one long_stories row. Should have embedding for kNN."""
    if not RAG_USE_ELASTICSEARCH:
        return
    client = get_elasticsearch_client()
    if client is None:
        return
    doc_id = _doc_id(doc)
    embedding = parse_embedding_from_db(doc.get("embedding"))
    if not doc_id or embedding is None:
        return
    es_doc = {
        "id": doc.get("id"),
        "ticker": _ticker_str(doc.get("ticker")),
        "title": doc.get("title") or "",
        "canonical_theme": doc.get("canonical_theme") or "",
        "summary": doc.get("summary") or "",
        "embedding": embedding,
    }
    try:
        client.index(index=LONG_STORIES_INDEX, id=doc_id, document=es_doc)
    except Exception as e:
        logger.debug("ES index long_story %s: %s", doc_id, e)


def bulk_index_news_articles(docs: List[Dict[str, Any]]) -> int:
    """Bulk index news_articles. Returns count indexed. Normalizes embedding from DB (pgvector string -> list)."""
    if not RAG_USE_ELASTICSEARCH or not docs:
        return 0
    client = get_elasticsearch_client()
    if client is None:
        return 0
    from elasticsearch import helpers
    actions = []
    for d in docs:
        embedding = parse_embedding_from_db(d.get("embedding"))
        if embedding is None:
            continue
        _id = str(d.get("id")) if d.get("id") is not None else None
        if not _id:
            continue
        actions.append({
            "_index": NEWS_ARTICLES_INDEX,
            "_id": _id,
            "_source": {
                "id": d.get("id"),
                "ticker": _ticker_str(d.get("ticker")),
                "title": d.get("title") or "",
                "summary": d.get("summary") or "",
                "url": d.get("url") or "",
                "published_at": d.get("published_at"),
                "source": d.get("source") or "",
                "embedding": embedding,
            },
        })
    if not actions:
        return 0
    try:
        success, errors = helpers.bulk(client, actions, raise_on_error=False, request_timeout=60)
        if success == 0 and isinstance(errors, list) and errors:
            for err in errors[:3]:
                logger.warning("ES bulk news_articles item error: %s", err)
        return success
    except Exception as e:
        logger.warning("ES bulk index news_articles: %s", e)
        return 0


def bulk_index_filing_chunks(docs: List[Dict[str, Any]]) -> int:
    """Bulk index sec_filing_chunks. Returns count indexed. Normalizes embedding from DB (pgvector string -> list)."""
    if not RAG_USE_ELASTICSEARCH or not docs:
        return 0
    client = get_elasticsearch_client()
    if client is None:
        return 0
    from elasticsearch import helpers
    actions = []
    for d in docs:
        embedding = parse_embedding_from_db(d.get("embedding"))
        if embedding is None:
            continue
        _id = str(d.get("id")) if d.get("id") is not None else None
        if not _id:
            continue
        actions.append({
            "_index": SEC_FILING_CHUNKS_INDEX,
            "_id": _id,
            "_source": {
                "id": d.get("id"),
                "filing_id": d.get("filing_id"),
                "ticker": _ticker_str(d.get("ticker")),
                "chunk_index": d.get("chunk_index", 0),
                "text": d.get("text") or "",
                "section": d.get("section"),
                "doc_type": d.get("doc_type"),
                "filed_date": d.get("filed_date"),
                "form_type": d.get("form_type"),
                "embedding": embedding,
            },
        })
    if not actions:
        return 0
    try:
        success, errors = helpers.bulk(client, actions, raise_on_error=False, request_timeout=60)
        if success == 0 and isinstance(errors, list) and errors:
            for err in errors[:3]:
                logger.warning("ES bulk filing_chunks item error: %s", err)
        return success
    except Exception as e:
        logger.warning("ES bulk index filing_chunks: %s", e)
        return 0


def bulk_index_macro_kb_chunks(docs: List[Dict[str, Any]]) -> int:
    """Bulk index macro_kb_chunks. Returns count indexed. Normalizes embedding from DB (pgvector string -> list)."""
    if not RAG_USE_ELASTICSEARCH or not docs:
        return 0
    client = get_elasticsearch_client()
    if client is None:
        return 0
    from elasticsearch import helpers
    actions = []
    for d in docs:
        embedding = parse_embedding_from_db(d.get("embedding"))
        if embedding is None:
            continue
        _id = str(d.get("id")) if d.get("id") is not None else None
        if not _id:
            continue
        actions.append({
            "_index": MACRO_KB_CHUNKS_INDEX,
            "_id": _id,
            "_source": {
                "id": d.get("id"),
                "book_id": d.get("book_id"),
                "chunk_index": d.get("chunk_index", 0),
                "text": d.get("text") or "",
                "embedding": embedding,
            },
        })
    if not actions:
        return 0
    try:
        success, errors = helpers.bulk(client, actions, raise_on_error=False, request_timeout=60)
        if success == 0 and isinstance(errors, list) and errors:
            for err in errors[:3]:
                logger.warning("ES bulk macro_kb_chunks item error: %s", err)
        return success
    except Exception as e:
        logger.warning("ES bulk index macro_kb_chunks: %s", e)
        return 0


def bulk_index_long_stories(docs: List[Dict[str, Any]]) -> int:
    """Bulk index long_stories (with embedding). Returns count indexed. Normalizes embedding from DB (pgvector string -> list)."""
    if not RAG_USE_ELASTICSEARCH or not docs:
        return 0
    client = get_elasticsearch_client()
    if client is None:
        return 0
    from elasticsearch import helpers
    actions = []
    for d in docs:
        embedding = parse_embedding_from_db(d.get("embedding"))
        if embedding is None:
            continue
        _id = str(d.get("id")) if d.get("id") is not None else None
        if not _id:
            continue
        actions.append({
            "_index": LONG_STORIES_INDEX,
            "_id": _id,
            "_source": {
                "id": d.get("id"),
                "ticker": _ticker_str(d.get("ticker")),
                "title": d.get("title") or "",
                "canonical_theme": d.get("canonical_theme") or "",
                "summary": d.get("summary") or "",
                "embedding": embedding,
            },
        })
    if not actions:
        return 0
    try:
        success, errors = helpers.bulk(client, actions, raise_on_error=False, request_timeout=60)
        if success == 0 and isinstance(errors, list) and errors:
            for err in errors[:3]:
                logger.warning("ES bulk long_stories item error: %s", err)
        return success
    except Exception as e:
        logger.warning("ES bulk index long_stories: %s", e)
        return 0
