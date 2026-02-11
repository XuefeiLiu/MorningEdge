"""
Store SEC 10-K/10-Q filings and chunks in Supabase.

Inserts sec_filings row (or gets existing by ticker+accession), then
inserts sec_filing_chunks with embeddings (batched).
Supports fiscal_year, period on filings; section, doc_type, source, is_boilerplate on chunks.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from supabase import Client

from backend.storage.embedding_utils import get_embeddings
from backend.storage.news_articles_save import _string_id_to_bigint

logger = logging.getLogger(__name__)


def filing_string_id(ticker: str, accession_number: str) -> str:
    """Stable string ID for sec_filings row (used for deterministic bigint id)."""
    return f"sec_filing_{ticker.strip().upper()}_{accession_number}"


def chunk_string_id(ticker: str, accession_number: str, chunk_index: int) -> str:
    """Stable string ID for sec_filing_chunks row (used for deterministic bigint id)."""
    return f"sec_filing_chunk_{ticker.strip().upper()}_{accession_number}_{chunk_index}"

EMBEDDING_BATCH_SIZE = 32


def derive_fiscal_year_period(filed_date: str, form_type: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Derive fiscal_year and period from filed_date (YYYY-MM-DD) and form_type.
    10-K -> FY + calendar year of filed_date (fiscal year end).
    10-Q -> Q1/Q2/Q3/Q4 + year from filed_date (quarter end).
    """
    if not filed_date or len(filed_date) < 10:
        return None, None
    try:
        y = int(filed_date[:4])
        m = int(filed_date[5:7]) if len(filed_date) >= 7 else 1
        form = (form_type or "").strip().upper()
        if form == "10-K":
            return y, "FY"
        if form == "10-Q":
            if m <= 3:
                return y, "Q1"
            if m <= 6:
                return y, "Q2"
            if m <= 9:
                return y, "Q3"
            return y, "Q4"
    except (ValueError, TypeError):
        pass
    return None, None


async def upsert_sec_filing(
    supabase: Client,
    ticker: str,
    form_type: str,
    filed_date: str,
    accession_number: str,
    url: Optional[str] = None,
    primary_document: Optional[str] = None,
    fiscal_year: Optional[int] = None,
    period: Optional[str] = None,
) -> Optional[int]:
    """
    Insert sec_filings row if not exists (by ticker+accession_number), return filing id.
    Derives fiscal_year and period from filed_date/form_type if not provided.
    """
    ticker = ticker.strip().upper()
    fy, pr = fiscal_year, period
    if fy is None or pr is None:
        derived_fy, derived_pr = derive_fiscal_year_period(filed_date, form_type)
        if fy is None:
            fy = derived_fy
        if pr is None:
            pr = derived_pr
    try:
        existing = (
            supabase.table("sec_filings")
            .select("id")
            .eq("ticker", ticker)
            .eq("accession_number", accession_number)
            .limit(1)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            return int(existing.data[0]["id"])
        filing_id = _string_id_to_bigint(filing_string_id(ticker, accession_number))
        row = {
            "id": filing_id,
            "ticker": ticker,
            "form_type": form_type,
            "filed_date": filed_date,
            "accession_number": accession_number,
            "url": url or "",
            "primary_document": primary_document or "",
            "fiscal_year": fy,
            "period": pr,
        }
        supabase.table("sec_filings").insert(row).execute()
        return filing_id
    except Exception as e:
        logger.error(f"upsert_sec_filing failed: {e}")
    return None


async def store_filing_chunks(
    supabase: Client,
    filing_id: int,
    ticker: str,
    chunks: List[Dict[str, Any]],
    accession_number: str,
) -> int:
    """
    Embed chunk texts in batches and insert into sec_filing_chunks.
    chunks: list of { "text": str, "metadata": { "ticker", "form_type", "filed_date", "chunk_index" } }.
    accession_number: used to build deterministic chunk id (sec_filing_chunk_{ticker}_{accession_number}_{chunk_index}).
    Returns number of chunks stored.
    """
    if not chunks:
        return 0
    ticker = ticker.strip().upper()
    accession_number = (accession_number or "").strip()
    all_embeddings: List[Optional[List[float]]] = []
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch_chunks = chunks[start : start + EMBEDDING_BATCH_SIZE]
        texts = [c["text"] for c in batch_chunks]
        emb_result = await get_embeddings(texts)
        if emb_result is not None and len(emb_result) == len(batch_chunks):
            all_embeddings.extend([row.tolist() for row in emb_result])
        else:
            all_embeddings.extend([None] * len(batch_chunks))
    if len(all_embeddings) != len(chunks):
        all_embeddings = [None] * len(chunks)
    rows = []
    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        idx = meta.get("chunk_index", i)
        emb = all_embeddings[i] if i < len(all_embeddings) else None
        chunk_id = _string_id_to_bigint(chunk_string_id(ticker, accession_number, idx))
        row = {
            "id": chunk_id,
            "filing_id": filing_id,
            "ticker": ticker,
            "chunk_index": idx,
            "text": chunk["text"],
            "embedding": emb,
        }
        if meta.get("section") is not None:
            row["section"] = meta["section"]
        if meta.get("doc_type") is not None:
            row["doc_type"] = meta["doc_type"]
        if meta.get("source") is not None:
            row["source"] = meta["source"]
        if meta.get("is_boilerplate") is not None:
            row["is_boilerplate"] = bool(meta["is_boilerplate"])
        rows.append(row)
    stored = 0
    for start in range(0, len(rows), EMBEDDING_BATCH_SIZE):
        batch = rows[start : start + EMBEDDING_BATCH_SIZE]
        try:
            supabase.table("sec_filing_chunks").insert(batch).execute()
            stored += len(batch)
        except Exception as e:
            logger.error(f"store_filing_chunks batch failed: {e}")
    return stored


def backfill_filing_metadata(supabase: Client) -> Tuple[int, int]:
    """
    One-off backfill: set fiscal_year and period on sec_filings where null;
    set doc_type and source on sec_filing_chunks where null (from parent filing).
    Returns (filings_updated, chunks_updated).
    """
    filings_updated = 0
    chunks_updated = 0
    try:
        rows = (
            supabase.table("sec_filings")
            .select("id, filed_date, form_type")
            .is_("fiscal_year", "null")
            .execute()
        )
        for r in (rows.data or []):
            fid = r.get("id")
            filed_date = r.get("filed_date") or ""
            form_type = r.get("form_type") or ""
            fy, pr = derive_fiscal_year_period(str(filed_date)[:10], form_type)
            if fy is None and pr is None:
                continue
            supabase.table("sec_filings").update({
                "fiscal_year": fy,
                "period": pr,
            }).eq("id", fid).execute()
            filings_updated += 1
        chunk_rows = (
            supabase.table("sec_filing_chunks")
            .select("id, filing_id")
            .is_("doc_type", "null")
            .execute()
        )
        if not chunk_rows.data:
            return filings_updated, 0
        filing_ids = list({r["filing_id"] for r in chunk_rows.data})
        filing_meta = (
            supabase.table("sec_filings")
            .select("id, form_type")
            .in_("id", filing_ids)
            .execute()
        )
        form_by_id = {r["id"]: (r.get("form_type") or "").strip() for r in (filing_meta.data or [])}
        for r in chunk_rows.data:
            cid = r.get("id")
            fid = r.get("filing_id")
            doc_type = form_by_id.get(fid) or "10-K"
            supabase.table("sec_filing_chunks").update({
                "doc_type": doc_type,
                "source": "SEC",
            }).eq("id", cid).execute()
            chunks_updated += 1
    except Exception as e:
        logger.error(f"backfill_filing_metadata failed: {e}")
    return filings_updated, chunks_updated
