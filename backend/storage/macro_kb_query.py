"""
Query operations for macro_kb_books and macro_kb_chunks (macro PDF KB for RAG).
"""
import logging
from typing import List, Dict, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_book_by_id(supabase: Client, book_id: int) -> Optional[Dict]:
    """Get macro_kb_books row by id."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_kb_books").select("*").eq("id", book_id).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"Error getting macro_kb_book {book_id}: {e}")
        return None


def get_book_by_source_uri(supabase: Client, source_uri: str) -> Optional[Dict]:
    """Get macro_kb_books row by source_uri."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_kb_books").select("*").eq("source_uri", source_uri).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"Error getting macro_kb_book by source_uri: {e}")
        return None


def list_books(supabase: Client) -> List[Dict]:
    """List all macro_kb_books."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_kb_books").select("*").order("created_at", desc=True).execute()
        return r.data if r.data else []
    except Exception as e:
        logger.error(f"Error listing macro_kb_books: {e}")
        return []


def get_chunks_with_null_embedding(
    supabase: Client,
    limit: Optional[int] = None,
    book_id: Optional[int] = None,
) -> List[Dict]:
    """Get macro_kb_chunks where embedding IS NULL (for backfill)."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        query = (
            supabase.table("macro_kb_chunks")
            .select("id, book_id, chunk_index, text")
            .is_("embedding", "null")
        )
        if book_id is not None:
            query = query.eq("book_id", book_id)
        query = query.order("book_id").order("chunk_index")
        if limit:
            query = query.limit(limit)
        r = query.execute()
        return list(r.data) if r.data else []
    except Exception as e:
        logger.error("Error getting macro_kb_chunks with null embedding: %s", e)
        return []


def get_chunks_by_book_id(supabase: Client, book_id: int, limit: Optional[int] = None) -> List[Dict]:
    """Get macro_kb_chunks for a book, ordered by chunk_index."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        query = supabase.table("macro_kb_chunks").select("*").eq("book_id", book_id).order("chunk_index")
        if limit:
            query = query.limit(limit)
        r = query.execute()
        return r.data if r.data else []
    except Exception as e:
        logger.error(f"Error getting macro_kb_chunks for book {book_id}: {e}")
        return []


def search_chunks_similar(
    supabase: Client,
    embedding: List[float],
    limit: int = 20,
    book_id: Optional[int] = None,
) -> List[Dict]:
    """
    Vector similarity search on macro_kb_chunks.embedding via RPC match_macro_kb_chunks.
    Returns chunks ordered by similarity (cosine). Run macro_kb_match_rpc.sql if RPC is missing.
    """
    if not supabase:
        supabase = get_supabase_client()
    if not embedding or len(embedding) != 1536:
        return []
    try:
        params = {"query_embedding": embedding, "match_count": limit}
        if book_id is not None:
            params["match_book_id"] = book_id
        r = supabase.rpc("match_macro_kb_chunks", params).execute()
        return list(r.data) if r.data else []
    except Exception as e:
        logger.error("Error searching macro_kb_chunks (ensure match_macro_kb_chunks RPC exists): %s", e)
        return []
