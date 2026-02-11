"""
Chunk SEC 10-K/10-Q full text for RAG storage.

Input: full text + metadata (ticker, form_type, filed_date).
Output: list of { "text": str, "metadata": { ticker, form_type, filed_date, chunk_index, section?, doc_type?, source? } }.
Uses character-based splitting with overlap; optionally section-aware (split by SEC Item headings).
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.config import (
    FILING_CHUNK_OVERLAP,
    FILING_CHUNK_OVERLAP_RATIO,
    FILING_CHUNK_SIZE,
    FILING_CHUNK_MAX_TOKENS,
)

logger = logging.getLogger(__name__)

# Approximate chars per token for English (used when token-based chunking)
CHARS_PER_TOKEN_ESTIMATE = 4


def _token_based_chunk_params() -> Tuple[int, int]:
    """Derive character-based chunk_size and overlap from token config (300-700 tokens, ~12% overlap)."""
    size_chars = FILING_CHUNK_MAX_TOKENS * CHARS_PER_TOKEN_ESTIMATE
    overlap_chars = int(size_chars * FILING_CHUNK_OVERLAP_RATIO)
    return size_chars, max(1, overlap_chars)

# SEC Item heading pattern: "Item 1.", "Item 1A.", "Item 7. Management's Discussion", etc.
_ITEM_HEADING_RE = re.compile(
    r"\n\s*Item\s+(\d+[A-Z]?)\s*[.\s]+([^\n]*)",
    re.IGNORECASE,
)


def _split_into_section_blocks(full_text: str) -> List[Tuple[Optional[str], str]]:
    """
    Split full filing text into (section_label, text) blocks by SEC Item headings.
    Text after an Item heading belongs to that section. Returns list of (section, text);
    section is e.g. "Item 7. MD&A" or None for preamble.
    """
    if not full_text or not full_text.strip():
        return []
    blocks: List[Tuple[Optional[str], str]] = []
    matches = list(_ITEM_HEADING_RE.finditer(full_text))
    if not matches:
        blocks.append((None, full_text.strip()))
        return blocks
    # Preamble before first Item
    first_start = matches[0].start()
    preamble = full_text[:first_start].strip()
    if preamble:
        blocks.append((None, preamble))
    for i, m in enumerate(matches):
        item_num = m.group(1).upper()
        rest = (m.group(2) or "").strip()
        if len(rest) > 60:
            rest = rest[:57] + "..."
        section_label = f"Item {item_num}. {rest}" if rest else f"Item {item_num}"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        text = full_text[start:end].strip()
        if text:
            blocks.append((section_label, text))
    return blocks


def _split_into_chunks(
    text: str,
    chunk_size: int = FILING_CHUNK_SIZE,
    chunk_overlap: int = FILING_CHUNK_OVERLAP,
) -> List[str]:
    """
    Split text into chunks by character count with overlap.
    Tries to break on paragraph boundaries (\n\n) when possible.
    """
    if not text or not text.strip():
        return []
    text = text.strip()
    if len(text) <= chunk_size:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        # Prefer breaking at paragraph boundary
        search_start = max(start, end - chunk_overlap - 200)
        paragraph_break = text.rfind("\n\n", search_start, end + 1)
        if paragraph_break > start:
            end = paragraph_break + 2
        else:
            # Break at last space in window
            last_space = text.rfind(" ", start, end + 1)
            if last_space > start:
                end = last_space + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - chunk_overlap if (end - chunk_overlap) > start else end
    return chunks


def chunk_filing_text(
    full_text: str,
    ticker: str,
    form_type: str,
    filed_date: str,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    section_aware: bool = True,
    source: str = "SEC",
    use_token_based: bool = True,
) -> List[Dict[str, Any]]:
    """
    Chunk full filing text and attach metadata for each chunk.
    When section_aware is True, splits by SEC Item headings and chunks within each section.
    When use_token_based is True, size and overlap are derived from FILING_CHUNK_MAX_TOKENS and
    FILING_CHUNK_OVERLAP_RATIO (target 300-700 tokens, ~10-15% overlap).

    Args:
        full_text: Extracted full text from SEC primary document.
        ticker: Stock ticker symbol.
        form_type: e.g. 10-K, 10-Q.
        filed_date: ISO date string (YYYY-MM-DD).
        chunk_size: Max characters per chunk (used if use_token_based=False).
        chunk_overlap: Overlap in characters (used if use_token_based=False).
        section_aware: If True, split by Item headings and tag chunks with section.
        source: Source label for chunks (e.g. SEC).
        use_token_based: If True, derive size/overlap from token config.

    Returns:
        List of dicts: { "text": str, "metadata": { ticker, form_type, filed_date, chunk_index, section?, doc_type, source } }.
    """
    if not full_text or not full_text.strip():
        logger.warning("Empty full_text in chunk_filing_text")
        return []
    if use_token_based:
        size_chars, overlap_chars = _token_based_chunk_params()
        chunk_size = chunk_size if chunk_size is not None else size_chars
        chunk_overlap = chunk_overlap if chunk_overlap is not None else overlap_chars
    else:
        chunk_size = chunk_size if chunk_size is not None else FILING_CHUNK_SIZE
        chunk_overlap = chunk_overlap if chunk_overlap is not None else FILING_CHUNK_OVERLAP
    ticker = ticker.strip().upper()
    doc_type = (form_type or "").strip()
    result: List[Dict[str, Any]] = []
    chunk_index = 0
    if section_aware:
        section_blocks = _split_into_section_blocks(full_text)
        for section_label, block_text in section_blocks:
            if not block_text.strip():
                continue
            text = re.sub(r"\s+", " ", block_text).strip()
            text = re.sub(r" \n ", "\n", text)
            raw_chunks = _split_into_chunks(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            for chunk_text in raw_chunks:
                if not chunk_text:
                    continue
                meta: Dict[str, Any] = {
                    "ticker": ticker,
                    "form_type": form_type,
                    "filed_date": filed_date,
                    "chunk_index": chunk_index,
                    "doc_type": doc_type,
                    "source": source,
                }
                if section_label is not None:
                    meta["section"] = section_label
                result.append({"text": chunk_text, "metadata": meta})
                chunk_index += 1
    else:
        text = re.sub(r"\s+", " ", full_text).strip()
        text = re.sub(r" \n ", "\n", text)
        raw_chunks = _split_into_chunks(
            text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        for chunk_text in raw_chunks:
            if not chunk_text:
                continue
            result.append({
                "text": chunk_text,
                "metadata": {
                    "ticker": ticker,
                    "form_type": form_type,
                    "filed_date": filed_date,
                    "chunk_index": chunk_index,
                    "doc_type": doc_type,
                    "source": source,
                },
            })
            chunk_index += 1
    logger.debug(f"Chunked filing {ticker} {form_type} into {len(result)} chunks")
    return result
