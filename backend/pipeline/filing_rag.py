"""
RAG retrieval over SEC filing chunks (10-K/10-Q).

Used for filing-in-storyline: embed storyline summary, retrieve similar filing chunks by ticker.
Hybrid scoring: similarity + recency decay + doc-type priority (10-Q recent > 10-K > older).
"""
import json
import ast
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional

import numpy as np
from supabase import Client

from backend.config import (
    RAG_FILING_SIMILARITY_WEIGHT,
    RAG_FILING_RECENCY_WEIGHT,
    RAG_FILING_DOC_PRIORITY_WEIGHT,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
CANDIDATE_MULTIPLIER = 3


def _parse_embedding(embedding) -> Optional[np.ndarray]:
    """Parse embedding from list, string, or array."""
    if embedding is None:
        return None
    if isinstance(embedding, list):
        return np.array(embedding, dtype=float)
    if isinstance(embedding, str):
        try:
            parsed = json.loads(embedding)
            return np.array(parsed, dtype=float)
        except (json.JSONDecodeError, ValueError):
            try:
                parsed = ast.literal_eval(embedding)
                return np.array(parsed, dtype=float)
            except (ValueError, SyntaxError):
                return None
    if isinstance(embedding, np.ndarray):
        return embedding.astype(float)
    return None


def _filed_date_parse(filed_date) -> Optional[datetime]:
    if not filed_date:
        return None
    try:
        return datetime.strptime(str(filed_date)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _recency_score(filed_dt: Optional[datetime], reference: datetime) -> float:
    """1 / (1 + years_since_filed); 1.0 if same day."""
    if filed_dt is None:
        return 0.5
    delta = reference - filed_dt
    years = max(0, delta.total_seconds() / (365.25 * 24 * 3600))
    return 1.0 / (1.0 + years)


def _doc_priority(form_type: Optional[str], filed_dt: Optional[datetime], reference: datetime) -> float:
    """10-Q recent > 10-K same year > older. Range ~0.5-1.0."""
    if not form_type:
        return 0.5
    form = form_type.strip().upper()
    rec = _recency_score(filed_dt, reference)
    if form == "10-Q":
        return 0.6 + 0.4 * rec
    if form == "10-K":
        return 0.5 + 0.3 * rec
    return 0.5


async def retrieve_similar_filing_chunks(
    supabase: Client,
    tickers: List[str],
    query_embedding: List[float],
    limit: int = DEFAULT_LIMIT,
    doc_types: Optional[List[str]] = None,
    sections: Optional[List[str]] = None,
    use_hybrid_score: bool = True,
    only_most_recent_filing: bool = False,
) -> List[Dict]:
    """
    Retrieve similar filing chunks by cosine similarity for given tickers.

    - Short story (only_most_recent_filing=True): query sec_filings ordered by filed_date desc,
      take the first two filings, then query sec_filing_chunks restricted to those filing_ids.
    - Long story (only_most_recent_filing=False): query all chunks for the tickers, then score
      by similarity and optional hybrid scoring.

    Optionally filter by doc_type, section. When use_hybrid_score is True,
    final_score = similarity * w_sim + recency_score * w_rec + doc_priority * w_doc.

    Returns:
        List of dicts: id, filing_id, ticker, chunk_index, text, similarity, final_score,
        and filing metadata (form_type, filed_date, section, doc_type) when joined to sec_filings.
    """
    if not query_embedding:
        return []
    q = _parse_embedding(query_embedding)
    if q is None:
        return []
    q_norm = np.linalg.norm(q)
    if q_norm <= 0:
        return []
    tickers_upper = [t.strip().upper() for t in tickers if t]
    if not tickers_upper:
        return []

    candidate_limit = limit * CANDIDATE_MULTIPLIER
    filing_meta: Dict[int, Dict] = {}
    most_recent_filing_ids: List[int] = []

    if only_most_recent_filing:
        # Short story: sec_filings ordered by filed_date desc, take the first two; then chunks for those filing_ids
        try:
            filings_query = (
                supabase.table("sec_filings")
                .select("id, ticker, form_type, filed_date, fiscal_year, period")
                .in_("ticker", tickers_upper)
                .order("filed_date", desc=True)
                .limit(2)
            )
            fresult = filings_query.execute()
            filings_data = fresult.data or []
        except Exception as e:
            logger.warning(f"retrieve_similar_filing_chunks sec_filings failed: {e}")
            return []
        if not filings_data:
            return []
        for f in filings_data:
            fid = f.get("id")
            fd = f.get("filed_date")
            if fid is not None:
                most_recent_filing_ids.append(int(fid))
                filing_meta[int(fid)] = {
                    "form_type": f.get("form_type"),
                    "filed_date": fd,
                    "fiscal_year": f.get("fiscal_year"),
                    "period": f.get("period"),
                }
        if not most_recent_filing_ids:
            return []
        try:
            query = (
                supabase.table("sec_filing_chunks")
                .select("id, filing_id, ticker, chunk_index, text, embedding, section, doc_type")
                .in_("filing_id", most_recent_filing_ids)
                .in_("ticker", tickers_upper)
                .not_.is_("embedding", "null")
                .limit(candidate_limit)
            )
            result = query.execute()
            rows = result.data if result.data else []
        except Exception as e:
            logger.warning(f"retrieve_similar_filing_chunks failed: {e}")
            return []
    else:
        # Long story: query chunks first, then get filing_meta for date filtering (filings around articles' published date)
        try:
            query = (
                supabase.table("sec_filing_chunks")
                .select("id, filing_id, ticker, chunk_index, text, embedding, section, doc_type")
                .in_("ticker", tickers_upper)
                .not_.is_("embedding", "null")
                .limit(candidate_limit)
            )
            result = query.execute()
            rows = result.data if result.data else []
        except Exception as e:
            logger.warning(f"retrieve_similar_filing_chunks failed: {e}")
            return []
        if not rows:
            return []
        filing_ids = list({r["filing_id"] for r in rows})
        try:
            fresult = (
                supabase.table("sec_filings")
                .select("id, form_type, filed_date, fiscal_year, period")
                .in_("id", filing_ids)
                .execute()
            )
            if fresult.data:
                for f in fresult.data:
                    filing_meta[int(f["id"])] = {
                        "form_type": f.get("form_type"),
                        "filed_date": f.get("filed_date"),
                        "fiscal_year": f.get("fiscal_year"),
                        "period": f.get("period"),
                    }
        except Exception:
            pass

    if not rows:
        return []
    reference = datetime.now(timezone.utc)
    scored = []
    for r in rows:
        meta = filing_meta.get(r.get("filing_id")) or {}
        filed_dt = _filed_date_parse(meta.get("filed_date"))
        form_type = meta.get("form_type") or r.get("doc_type")
        if doc_types and form_type and form_type.strip().upper() not in [d.strip().upper() for d in doc_types]:
            continue
        section = r.get("section")
        if sections and section and section not in sections:
            continue
        emb = _parse_embedding(r.get("embedding"))
        if emb is None:
            continue
        norm = np.linalg.norm(emb)
        if norm <= 0:
            continue
        sim = float(np.dot(q, emb) / (q_norm * norm))
        rec_score = _recency_score(filed_dt, reference)
        doc_pri = _doc_priority(form_type, filed_dt, reference)
        if use_hybrid_score:
            final = (
                sim * RAG_FILING_SIMILARITY_WEIGHT
                + rec_score * RAG_FILING_RECENCY_WEIGHT
                + doc_pri * RAG_FILING_DOC_PRIORITY_WEIGHT
            )
        else:
            final = sim
        out = dict(r)
        out["similarity"] = sim
        out["final_score"] = final
        out["form_type"] = form_type or r.get("doc_type")
        out["filed_date"] = meta.get("filed_date")
        out["fiscal_year"] = meta.get("fiscal_year")
        out["period"] = meta.get("period")
        if not out.get("section") and r.get("section"):
            out["section"] = r["section"]
        scored.append(out)
    scored.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return scored[:limit]
