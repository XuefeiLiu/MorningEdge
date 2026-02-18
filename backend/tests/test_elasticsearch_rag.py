"""Tests for Elasticsearch RAG (hybrid search) fallback when ES is disabled or client unavailable."""
import pytest


class TestElasticsearchHybridSearchFallback:
    def test_search_news_hybrid_returns_empty_when_client_none(self):
        from backend.services.elasticsearch_hybrid_search import search_news_hybrid
        result = search_news_hybrid(
            None,
            query_text="test",
            query_embedding=[0.1] * 1536,
            tickers=["AAPL"],
            limit=10,
        )
        assert result == []

    def test_find_similar_long_story_hybrid_returns_none_when_client_none(self):
        from backend.services.elasticsearch_hybrid_search import find_similar_long_story_hybrid
        result = find_similar_long_story_hybrid(
            None,
            ticker="AAPL",
            query_embedding=[0.1] * 1536,
        )
        assert result is None

    def test_ensure_indices_handles_none_client(self):
        from backend.storage.elasticsearch_indices import ensure_indices
        ensure_indices(None)  # should not raise
