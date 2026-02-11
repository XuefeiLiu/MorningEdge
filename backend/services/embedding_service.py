"""
Centralized Embedding Service

Uses OpenAI text-embedding-3-small (1536-dim, matches DB vector(1536)).
Batching: send many texts per call via client.embeddings.create(input=texts).
Retries on 429 (rate limit) with backoff parsed from error or default 2s.
"""
import asyncio
import logging
import re
import numpy as np
from typing import List, Optional

from openai import AsyncOpenAI

from backend.config import (
    EMBEDDING_DIMENSION,
    EMBEDDING_TIMEOUT,
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Centralized service for generating embeddings via OpenAI
    (text-embedding-3-small, 1536-dim).
    """

    def __init__(self):
        """Initialize the embedding service."""
        self.available = bool(OPENAI_API_KEY)
        self._client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        if not self.available:
            logger.warning(
                "EmbeddingService: OPENAI_API_KEY is required for embeddings (text-embedding-3-small, 1536-dim)."
            )
        else:
            logger.info("EmbeddingService initialized with OpenAI (%s)", OPENAI_EMBEDDING_MODEL)

    async def get_embeddings(
        self,
        texts: List[str],
        timeout: Optional[float] = None
    ) -> Optional[np.ndarray]:
        """
        Get embeddings for a list of texts (batched: many texts per call).

        Args:
            texts: List of text strings to embed
            timeout: Request timeout in seconds

        Returns:
            numpy array of embeddings (n_texts, embedding_dim) or None if failed
        """
        if not texts:
            return None
        if not self.available:
            logger.error("No embedding provider: OPENAI_API_KEY not set")
            return None
        t = timeout if timeout is not None else EMBEDDING_TIMEOUT
        return await self._get_embeddings_openai(texts, timeout=t)

    async def _get_embeddings_openai(
        self,
        texts: List[str],
        timeout: float = 90.0
    ) -> Optional[np.ndarray]:
        """
        Get embeddings via OpenAI embeddings API.
        Model text-embedding-3-small returns 1536-dim vectors (matches DB).
        Retries on 429 (rate limit) up to 5 times with backoff from error or 2s.
        """
        if not self._client:
            return None
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = await self._client.embeddings.create(
                    model=OPENAI_EMBEDDING_MODEL,
                    input=texts,
                    timeout=timeout,
                )
                if not resp.data or len(resp.data) != len(texts):
                    logger.error(
                        "OpenAI embedding response length %s does not match %d texts",
                        len(resp.data) if resp.data else 0,
                        len(texts),
                    )
                    return None
                embeddings = np.array([e.embedding for e in resp.data], dtype=np.float32)
                if embeddings.shape[1] != EMBEDDING_DIMENSION:
                    logger.warning(
                        "OpenAI model %s returned %d-dim vectors; DB expects %d.",
                        OPENAI_EMBEDDING_MODEL,
                        embeddings.shape[1],
                        EMBEDDING_DIMENSION,
                    )
                logger.debug("Got embeddings shape %s from OpenAI", embeddings.shape)
                return embeddings
            except Exception as e:
                msg = str(e).strip() if str(e) else "(no message)"
                is_rate_limit = "429" in msg or "rate_limit" in msg.lower()
                if is_rate_limit and attempt < max_retries - 1:
                    # Parse "Please try again in 1.189s" or similar
                    wait_s = 2.0
                    match = re.search(r"try again in ([\d.]+)\s*s", msg, re.I)
                    if match:
                        try:
                            wait_s = max(1.0, float(match.group(1)) + 0.5)
                        except (ValueError, TypeError):
                            pass
                    logger.warning(
                        "OpenAI rate limit (429), waiting %.1fs before retry %d/%d",
                        wait_s, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(wait_s)
                    continue
                logger.error(
                    "Error getting embeddings from OpenAI: %s (model=%s)",
                    msg,
                    OPENAI_EMBEDDING_MODEL,
                    exc_info=not msg or msg == "(no message)",
                )
                return None
        return None

    def cosine_similarity(
        self,
        vec1: np.ndarray,
        vec2: np.ndarray
    ) -> float:
        """
        Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Cosine similarity score (0-1)
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def normalize_embeddings(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Normalize embeddings for efficient cosine similarity calculation.

        Args:
            embeddings: numpy array of embeddings (n_texts, embedding_dim)

        Returns:
            Normalized embeddings array
        """
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        return embeddings / norms

    def compute_similarity_matrix(
        self,
        embeddings1: np.ndarray,
        embeddings2: np.ndarray
    ) -> np.ndarray:
        """
        Compute pairwise cosine similarity matrix between two sets of embeddings.

        Args:
            embeddings1: First set of embeddings (n1, embedding_dim)
            embeddings2: Second set of embeddings (n2, embedding_dim)

        Returns:
            Similarity matrix (n1, n2) where entry (i, j) is cosine similarity
            between embeddings1[i] and embeddings2[j]
        """
        normalized1 = self.normalize_embeddings(embeddings1)
        normalized2 = self.normalize_embeddings(embeddings2)

        # Matrix multiplication: (n1, dim) @ (dim, n2) = (n1, n2)
        similarity_matrix = np.dot(normalized1, normalized2.T)

        return similarity_matrix


# Global singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """
    Get the global embedding service instance (singleton pattern).

    Returns:
        EmbeddingService instance
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


async def get_embeddings(
    texts: List[str],
    timeout: Optional[float] = None
) -> Optional[np.ndarray]:
    """
    Get embeddings for a list of texts (OpenAI text-embedding-3-small, 1536-dim).

    Args:
        texts: List of text strings to embed
        timeout: Request timeout in seconds

    Returns:
        numpy array of embeddings (n_texts, embedding_dim) or None if failed
    """
    service = get_embedding_service()
    return await service.get_embeddings(texts, timeout=timeout)
