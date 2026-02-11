"""
Macro KB retrieval: embed query text, vector search macro_kb_chunks, optional rerank.
"""
import asyncio
import logging
from typing import List, Dict, Optional

from backend.config import MACRO_KB_RERANK_TOP_K, MACRO_KB_RETRIEVAL_TOP_K
from backend.storage.embedding_utils import get_embeddings
from backend.storage.macro_kb_query import search_chunks_similar
from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


async def retrieve_chunks_async(
    query_text: str,
    supabase=None,
    top_k: Optional[int] = None,
    rerank_top: Optional[int] = None,
    book_id: Optional[int] = None,
) -> List[Dict]:
    """
    Embed query_text, run vector search on macro_kb_chunks, return top chunks.
    top_k: retrieval limit (default MACRO_KB_RETRIEVAL_TOP_K). rerank_top: optional slice after retrieval.
    """
    if not query_text or not query_text.strip():
        return []
    top_k = top_k or MACRO_KB_RETRIEVAL_TOP_K
    if supabase is None:
        supabase = get_supabase_client()
    embeddings = await get_embeddings([query_text.strip()])
    if embeddings is None or embeddings.shape[0] == 0:
        return []
    embedding = embeddings[0].tolist()
    chunks = search_chunks_similar(supabase, embedding, limit=top_k, book_id=book_id)
    if rerank_top is not None and rerank_top > 0 and len(chunks) > rerank_top:
        chunks = chunks[:rerank_top]
    return chunks


def retrieve_chunks_sync(
    query_text: str,
    supabase=None,
    top_k: Optional[int] = None,
    rerank_top: Optional[int] = None,
    book_id: Optional[int] = None,
) -> List[Dict]:
    """Synchronous wrapper for retrieve_chunks_async."""
    return asyncio.run(retrieve_chunks_async(query_text, supabase, top_k, rerank_top, book_id))
