"""
News Pipeline Package

Active pipeline: backend.pipeline.overnight_pipeline.runner

Shared modules:
- rag_retrieval: Retrieve similar articles using embedding similarity
- rerank: Rerank candidates with local cross-encoder
- long_story_service: Create and manage long stories
- maybe_merge_or_create_long_story: Merge into or create long stories
"""

from backend.pipeline.rerank import rerank, rerank_top_n_recent, rerank_top_n_history

__all__ = ["rerank", "rerank_top_n_recent", "rerank_top_n_history"]
