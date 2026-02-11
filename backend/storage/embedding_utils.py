"""
Shared utility for getting embeddings.

Delegates to the centralized embedding service (OpenAI text-embedding-3-small, 1536-dim).
Also provides parse_embedding_from_db for normalizing embeddings read from Supabase/PostgREST
(pgvector often returned as string "[0.1, -0.2, ...]").
"""
import json
from typing import Any, List, Optional

import numpy as np

from backend.services.embedding_service import get_embeddings as _get_embeddings


def parse_embedding_from_db(embedding: Any) -> Optional[List[float]]:
    """
    Convert embedding from DB/Supabase (list or pgvector string) to list of floats.
    Use wherever we read an embedding column from PostgREST (news_articles, sec_filing_chunks, etc.).
    """
    if embedding is None:
        return None
    if isinstance(embedding, list):
        try:
            return [float(x) for x in embedding]
        except (TypeError, ValueError):
            return None
    if isinstance(embedding, str):
        try:
            parsed = json.loads(embedding)
            return [float(x) for x in parsed] if isinstance(parsed, list) else None
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    return None


async def get_embeddings(texts: List[str]) -> Optional[np.ndarray]:
    """
    Get embeddings for a list of texts using OpenAI text-embedding-3-small (1536-dim).

    Args:
        texts: List of text strings to embed

    Returns:
        numpy array of embeddings (n_texts, embedding_dim) or None if failed
    """
    return await _get_embeddings(texts)
