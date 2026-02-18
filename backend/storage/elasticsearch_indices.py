"""
Elasticsearch index mappings for hybrid RAG (BM25 + kNN).
Embedding dim 1536 (OpenAI text-embedding-3-small); similarity: cosine.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

INDEX_PREFIX = "morningedge"

# Index names (with optional prefix for env-specific deployments)
def _name(base: str) -> str:
    return f"{INDEX_PREFIX}_{base}" if INDEX_PREFIX else base

NEWS_ARTICLES_INDEX = _name("news_articles")
SEC_FILING_CHUNKS_INDEX = _name("sec_filing_chunks")
MACRO_KB_CHUNKS_INDEX = _name("macro_kb_chunks")
LONG_STORIES_INDEX = _name("long_stories")

EMBEDDING_DIM = 1536


def _dense_vector_mapping(dims: int = EMBEDDING_DIM) -> Dict[str, Any]:
    return {
        "type": "dense_vector",
        "dims": dims,
        "index": True,
        "similarity": "cosine",
    }


def get_news_articles_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "id": {"type": "long"},
            "ticker": {"type": "keyword"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "url": {"type": "keyword"},
            "published_at": {"type": "date"},
            "source": {"type": "keyword"},
            "embedding": _dense_vector_mapping(),
        }
    }


def get_sec_filing_chunks_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "id": {"type": "long"},
            "filing_id": {"type": "long"},
            "ticker": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "text": {"type": "text"},
            "section": {"type": "keyword"},
            "doc_type": {"type": "keyword"},
            "filed_date": {"type": "date"},
            "form_type": {"type": "keyword"},
            "embedding": _dense_vector_mapping(),
        }
    }


def get_macro_kb_chunks_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "id": {"type": "long"},
            "book_id": {"type": "long"},
            "chunk_index": {"type": "integer"},
            "text": {"type": "text"},
            "embedding": _dense_vector_mapping(),
        }
    }


def get_long_stories_mapping() -> Dict[str, Any]:
    return {
        "properties": {
            "id": {"type": "long"},
            "ticker": {"type": "keyword"},
            "title": {"type": "text"},
            "canonical_theme": {"type": "text"},
            "summary": {"type": "text"},
            "embedding": _dense_vector_mapping(),
        }
    }


def ensure_indices(client) -> None:
    """
    Create the four RAG indices if they do not exist.
    Idempotent: safe to call on every startup or backfill.
    """
    if client is None:
        return
    indices = [
        (NEWS_ARTICLES_INDEX, get_news_articles_mapping()),
        (SEC_FILING_CHUNKS_INDEX, get_sec_filing_chunks_mapping()),
        (MACRO_KB_CHUNKS_INDEX, get_macro_kb_chunks_mapping()),
        (LONG_STORIES_INDEX, get_long_stories_mapping()),
    ]
    for index_name, mapping in indices:
        try:
            if not client.indices.exists(index=index_name):
                client.indices.create(
                    index=index_name,
                    body={"mappings": mapping},
                )
                logger.info("Created Elasticsearch index: %s", index_name)
        except Exception as e:
            logger.warning("Failed to create index %s: %s", index_name, e)
