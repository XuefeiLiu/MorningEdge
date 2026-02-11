"""
Conditional filing linkage: when story is_filing_related, pick the single most recent
qualifying filing by sec_filings.filed_date (latest row), store story_filing_link,
optionally add top-k chunks to story_evidence_chunk_link.
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

import numpy as np
from supabase import Client

from backend.services.embedding_service import get_embedding_service
from backend.storage.embedding_utils import parse_embedding_from_db
from backend.pipeline.overnight_pipeline.config import FILING_CHUNK_TOP_K

logger = logging.getLogger(__name__)


def get_most_recent_filing(
    supabase: Client,
    ticker: str,
    form_types: Optional[List[str]] = None,
    max_filed_date: Optional[date] = None,
) -> Optional[Dict]:
    """
    Pick the single most recent filing by sec_filings.filed_date: ticker match, optional form_type.
    "Most recent" = the row with the latest filed_date in the dataset (order by filed_date desc, limit 1).
    Optionally restrict to filings with filed_date <= max_filed_date (e.g. story date).
    Returns one row with id, ticker, form_type, filed_date or None.
    """
    if not ticker or not ticker.strip():
        return None
    ticker = ticker.strip().upper()
    try:
        query = (
            supabase.table("sec_filings")
            .select("id, ticker, form_type, filed_date")
            .eq("ticker", ticker)
            .order("filed_date", desc=True)
            .limit(1)
        )
        if max_filed_date is not None:
            query = query.lte("filed_date", max_filed_date.isoformat())
        if form_types:
            form_list = [f.strip().upper() for f in form_types if f and str(f).strip()]
            if form_list:
                query = query.in_("form_type", form_list)
        r = query.execute()
        if r.data and len(r.data) > 0:
            return r.data[0]
    except Exception as e:
        logger.warning("get_most_recent_filing failed: %s", e)
    return None


async def get_top_chunks_for_filing(
    supabase: Client,
    filing_id: int,
    query_embedding: List[float],
    top_k: int = FILING_CHUNK_TOP_K,
) -> List[Dict[str, Any]]:
    """
    Fetch chunks for filing_id, rank by cosine similarity to query_embedding, return top_k.
    Each item: { "chunk_id", "score", "excerpt_text" }.
    """
    try:
        r = (
            supabase.table("sec_filing_chunks")
            .select("id, text, embedding")
            .eq("filing_id", filing_id)
            .execute()
        )
    except Exception as e:
        logger.warning("Failed to fetch chunks for filing %s: %s", filing_id, e)
        return []
    rows = r.data or []
    if not rows or not query_embedding:
        return []
    q = np.array(query_embedding, dtype=np.float32).reshape(1, -1)
    svc = get_embedding_service()
    embeddings = []
    valid_rows = []
    for row in rows:
        vec = parse_embedding_from_db(row.get("embedding"))
        if vec is None:
            continue
        embeddings.append(vec)
        valid_rows.append(row)
    if not valid_rows:
        return []
    emb_arr = np.array(embeddings, dtype=np.float32)
    sim = svc.compute_similarity_matrix(q, emb_arr)[0]
    order = np.argsort(-sim)[:top_k]
    out = []
    for idx in order:
        row = valid_rows[idx]
        out.append({
            "chunk_id": row["id"],
            "score": float(sim[idx]),
            "excerpt_text": (row.get("text") or ""),
        })
    return out
