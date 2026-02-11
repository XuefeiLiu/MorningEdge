"""
Macro KB ingestion: discover PDFs, extract text (with page boundaries), chunk, embed, save to macro_kb_books + macro_kb_chunks.

Config: MACRO_KB_PDF_PATH (folder or single file), MACRO_KB_CHUNK_*.
Chunking: token-based (800–1200 default, overlap ~15%, max 1500); page_start/page_end from extraction.
"""
import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import (
    MACRO_KB_CHUNK_HARD_MAX_TOKENS,
    MACRO_KB_CHUNK_MAX_TOKENS,
    MACRO_KB_CHUNK_OVERLAP_RATIO,
    MACRO_KB_PDF_PATH,
)
from backend.storage.embedding_utils import get_embeddings
from backend.storage.macro_kb_save import upsert_book, upsert_chunks_batch
from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN_ESTIMATE = 4
# Batch size for embedding API (avoids timeouts / rate limits; OpenAI supports many per request but batching is safer)
EMBED_BATCH_SIZE = 50


def _pdf_extract_with_pages(pdf_path: str) -> Tuple[str, List[Tuple[int, int, int]]]:
    """
    Extract full text and page boundaries (page_num, start_char, end_char) using PyMuPDF.
    Returns (full_text, [(page_num, start, end), ...]).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("pymupdf is required for macro KB ingest; pip install pymupdf")
    doc = fitz.open(pdf_path)
    full_parts: List[str] = []
    boundaries: List[Tuple[int, int, int]] = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()
        start = sum(len(p) for p in full_parts) + (2 if full_parts else 0)  # \n\n between pages
        full_parts.append(text)
        end = start + len(text)
        boundaries.append((page_num + 1, start, end))
    full_text = "\n\n".join(full_parts)
    doc.close()
    return full_text, boundaries


def _token_based_chunk_params() -> Tuple[int, int]:
    """Character size and overlap from MACRO_KB_* token config."""
    size_chars = MACRO_KB_CHUNK_MAX_TOKENS * CHARS_PER_TOKEN_ESTIMATE
    overlap_chars = int(size_chars * MACRO_KB_CHUNK_OVERLAP_RATIO)
    return size_chars, max(1, overlap_chars)


def _page_range_for_span(
    start: int, end: int, boundaries: List[Tuple[int, int, int]]
) -> Tuple[Optional[int], Optional[int]]:
    """Map character span (start, end) to (page_start, page_end) from boundaries."""
    if not boundaries:
        return None, None
    page_start = page_end = None
    for page_num, b_start, b_end in boundaries:
        if b_end > start and b_start < end:
            if page_start is None:
                page_start = page_num
            page_end = page_num
    return page_start, page_end


def _split_into_chunks_with_positions(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    hard_max_chars: Optional[int] = None,
) -> List[Tuple[str, int, int]]:
    """Split text into chunks by character count with overlap; return (chunk_str, start, end) in original text."""
    if not text or not text.strip():
        return []
    text = text.strip()
    hard = (hard_max_chars or chunk_size * 2) if hard_max_chars else chunk_size * 2
    chunks: List[Tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end - start > hard:
            end = start + hard
        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append((chunk, start, len(text)))
            break
        search_start = max(start, end - chunk_overlap - 200)
        paragraph_break = text.rfind("\n\n", search_start, end + 1)
        if paragraph_break > start:
            end = paragraph_break + 2
        else:
            last_space = text.rfind(" ", start, end + 1)
            if last_space > start:
                end = last_space + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append((chunk, start, end))
        start = end - chunk_overlap if (end - chunk_overlap) > start else end
    return chunks


def chunk_pdf_text(
    full_text: str,
    page_boundaries: List[Tuple[int, int, int]],
    source_uri: str,
) -> List[Dict[str, Any]]:
    """
    Chunk full PDF text with token-based size; attach page_start, page_end, chunk_type.
    Returns list of { text, chunk_index, page_start, page_end, chunk_type, is_boilerplate }.
    """
    if not full_text or not full_text.strip():
        return []
    size_chars, overlap_chars = _token_based_chunk_params()
    hard_max_chars = MACRO_KB_CHUNK_HARD_MAX_TOKENS * CHARS_PER_TOKEN_ESTIMATE
    raw_with_pos = _split_into_chunks_with_positions(
        full_text,
        chunk_size=size_chars,
        chunk_overlap=overlap_chars,
        hard_max_chars=hard_max_chars,
    )
    result: List[Dict[str, Any]] = []
    for i, (chunk_text, start, end) in enumerate(raw_with_pos):
        if not chunk_text:
            continue
        page_start, page_end = _page_range_for_span(start, end, page_boundaries)
        # Normalize whitespace for storage
        text_stored = re.sub(r"\s+", " ", chunk_text).strip()
        result.append({
            "chunk_index": i,
            "text": text_stored,
            "page_start": page_start,
            "page_end": page_end,
            "chunk_type": "narrative",
            "is_boilerplate": False,
        })
    return result


def list_pdf_paths(path_config: str) -> List[str]:
    """Resolve MACRO_KB_PDF_PATH to a list of PDF file paths (folder or single file)."""
    path = Path(path_config).expanduser().resolve()
    if not path.exists():
        logger.warning("Macro KB path does not exist: %s", path)
        return []
    if path.is_file():
        if path.suffix.lower() == ".pdf":
            return [str(path)]
        return []
    return sorted(str(p) for p in path.glob("*.pdf"))


async def ingest_one_pdf(
    pdf_path: str,
    supabase=None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    edition: Optional[str] = None,
) -> Tuple[int, int]:
    """
    Extract, chunk, embed, and save one PDF to macro_kb_books + macro_kb_chunks.
    Returns (book_id, chunks_saved).
    """
    if supabase is None:
        supabase = get_supabase_client()
    source_uri = f"file://{os.path.abspath(pdf_path)}"
    full_text, page_boundaries = _pdf_extract_with_pages(pdf_path)
    if not full_text.strip():
        logger.warning("No text extracted from %s", pdf_path)
        return 0, 0
    chunks_meta = chunk_pdf_text(full_text, page_boundaries, source_uri)
    if not chunks_meta:
        logger.warning("No chunks from %s", pdf_path)
        return 0, 0
    book_id = upsert_book(
        supabase,
        source_uri=source_uri,
        title=title or Path(pdf_path).stem,
        author=author or "",
        edition=edition or "",
    )
    if not book_id:
        logger.error("Failed to upsert book for %s", pdf_path)
        return 0, 0
    texts = [c["text"] for c in chunks_meta]
    # Embed in batches to avoid timeouts / rate limits; assign into chunks_meta
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        end = min(start + EMBED_BATCH_SIZE, len(texts))
        batch_texts = texts[start:end]
        emb_arr = await get_embeddings(batch_texts)
        if emb_arr is not None and emb_arr.shape[0] == len(batch_texts):
            for i, c in enumerate(chunks_meta[start:end]):
                c["embedding"] = emb_arr[i].tolist()
        else:
            logger.warning(
                "Embedding batch failed for %s chunks %d-%d (of %d); those chunks will have null embedding",
                pdf_path, start, end, len(texts),
            )
    chunks_with_embedding = [
        {
            "chunk_index": c["chunk_index"],
            "text": c["text"],
            "embedding": c.get("embedding"),
            "page_start": c.get("page_start"),
            "page_end": c.get("page_end"),
            "chunk_type": c.get("chunk_type", "narrative"),
            "is_boilerplate": c.get("is_boilerplate", False),
        }
        for c in chunks_meta
    ]
    count = upsert_chunks_batch(
        supabase,
        book_id=book_id,
        chunks=chunks_with_embedding,
        source_uri=source_uri,
    )
    logger.info("Ingested %s: book_id=%s, chunks=%s", pdf_path, book_id, count)
    return book_id, count


async def ingest_macro_kb(
    path: Optional[str] = None,
    supabase=None,
) -> Dict[str, Any]:
    """
    Discover PDFs at path (default MACRO_KB_PDF_PATH), ingest each into macro_kb_books + macro_kb_chunks.
    Returns { "books": N, "chunks": M, "paths": [...] }.
    """
    path = path or MACRO_KB_PDF_PATH
    pdf_paths = list_pdf_paths(path)
    if not pdf_paths:
        return {"books": 0, "chunks": 0, "paths": []}
    if supabase is None:
        supabase = get_supabase_client()
    total_books = 0
    total_chunks = 0
    for pdf_path in pdf_paths:
        try:
            bid, cnt = await ingest_one_pdf(pdf_path, supabase=supabase)
            if bid:
                total_books += 1
            total_chunks += cnt
        except Exception as e:
            logger.exception("Failed to ingest %s: %s", pdf_path, e)
    return {"books": total_books, "chunks": total_chunks, "paths": pdf_paths}


def run_ingest_sync(path: Optional[str] = None) -> Dict[str, Any]:
    """Synchronous entry point for scripts."""
    return asyncio.run(ingest_macro_kb(path=path))
