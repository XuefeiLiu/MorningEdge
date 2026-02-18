"""
Save operations for macro_kb_books and macro_kb_chunks (macro PDF KB).
ID: application supplies id via _string_id_to_bigint(macro_book_string_id / macro_chunk_string_id).
"""
import logging
from typing import List, Dict, Any, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.macro_id_utils import (
    _string_id_to_bigint,
    macro_book_string_id,
    macro_chunk_string_id,
)

logger = logging.getLogger(__name__)


def upsert_book(
    supabase: Client,
    source_uri: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    edition: Optional[str] = None,
) -> Optional[int]:
    """Upsert macro_kb_books row; return book id."""
    if not supabase:
        supabase = get_supabase_client()
    string_id = macro_book_string_id(source_uri)
    db_id = _string_id_to_bigint(string_id)
    row = {
        "id": db_id,
        "title": title or "",
        "author": author or "",
        "edition": edition or "",
        "source_uri": source_uri,
    }
    try:
        supabase.table("macro_kb_books").upsert(row, on_conflict="id").execute()
        return db_id
    except Exception as e:
        logger.error(f"Failed to upsert macro_kb_book {source_uri}: {e}")
        return None


def upsert_chunk(
    supabase: Client,
    book_id: int,
    chunk_index: int,
    text: str,
    embedding: Optional[List[float]] = None,
    chapter: Optional[str] = None,
    section: Optional[str] = None,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    chunk_type: Optional[str] = None,
    is_boilerplate: bool = False,
    source_uri: Optional[str] = None,
) -> Optional[int]:
    """Upsert one macro_kb_chunks row; return chunk id. Use source_uri for stable chunk string ID when provided."""
    if not supabase:
        supabase = get_supabase_client()
    if source_uri:
        book_string_id = macro_book_string_id(source_uri)
    else:
        book_string_id = f"macro_book_{_hash_12(str(book_id))}"
    string_id = macro_chunk_string_id(book_string_id, chunk_index)
    db_id = _string_id_to_bigint(string_id)
    row = {
        "id": db_id,
        "book_id": book_id,
        "chunk_index": chunk_index,
        "text": text,
        "chapter": chapter,
        "section": section,
        "page_start": page_start,
        "page_end": page_end,
        "chunk_type": chunk_type or "narrative",
        "is_boilerplate": is_boilerplate,
    }
    if embedding is not None:
        row["embedding"] = embedding
    try:
        supabase.table("macro_kb_chunks").upsert(row, on_conflict="id").execute()
        try:
            from backend.storage.elasticsearch_sync import index_macro_kb_chunk
            index_macro_kb_chunk(row)
        except Exception:
            pass
        return db_id
    except Exception as e:
        logger.error(f"Failed to upsert macro_kb_chunk book_id={book_id} idx={chunk_index}: {e}")
        return None


def _hash_12(s: str) -> str:
    from hashlib import md5
    return md5(s.encode("utf-8")).hexdigest()[:12]


def upsert_chunks_batch(
    supabase: Client,
    book_id: int,
    chunks: List[Dict[str, Any]],
    source_uri: Optional[str] = None,
) -> int:
    """
    Upsert multiple chunks for a book. Each chunk: chunk_index, text, embedding?, chapter?, section?, page_start?, page_end?, chunk_type?, is_boilerplate?.
    Pass source_uri for stable chunk string IDs (macro_chunk_{book_string_id}_{index}).
    """
    count = 0
    for c in chunks:
        idx = c.get("chunk_index", 0)
        if upsert_chunk(
            supabase,
            book_id=book_id,
            chunk_index=idx,
            text=c.get("text", ""),
            embedding=c.get("embedding"),
            chapter=c.get("chapter"),
            section=c.get("section"),
            page_start=c.get("page_start"),
            page_end=c.get("page_end"),
            chunk_type=c.get("chunk_type"),
            is_boilerplate=c.get("is_boilerplate", False),
            source_uri=source_uri,
        ) is not None:
            count += 1
    return count
