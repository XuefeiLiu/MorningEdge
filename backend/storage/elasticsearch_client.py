"""
Elasticsearch client for optional hybrid RAG (BM25 + kNN).
Returns None when ELASTICSEARCH_URL is unset or client is unhealthy; callers fall back to Supabase.
"""
import logging
from typing import Optional, Any

from backend.config import ELASTICSEARCH_URL, ELASTICSEARCH_API_KEY

logger = logging.getLogger(__name__)

_es_client: Optional[Any] = None


def get_elasticsearch_client():
    """
    Get or create Elasticsearch client. Returns None if ELASTICSEARCH_URL is unset
    or if the client fails to connect (callers should fall back to Supabase).
    """
    global _es_client
    if not ELASTICSEARCH_URL:
        return None
    if _es_client is not None:
        return _es_client
    try:
        from elasticsearch import Elasticsearch
        if ELASTICSEARCH_API_KEY:
            client = Elasticsearch(ELASTICSEARCH_URL, api_key=ELASTICSEARCH_API_KEY)
        else:
            client = Elasticsearch(ELASTICSEARCH_URL)
        if not client.ping():
            logger.warning("Elasticsearch ping failed at %s", ELASTICSEARCH_URL)
            return None
        _es_client = client
        logger.info("Connected to Elasticsearch: %s", ELASTICSEARCH_URL)
        return _es_client
    except Exception as e:
        logger.warning("Elasticsearch client unavailable: %s", e)
        return None


def reset_elasticsearch_client() -> None:
    """Reset the global client (useful for testing)."""
    global _es_client
    _es_client = None
