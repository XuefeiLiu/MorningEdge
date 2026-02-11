"""
Insert into story table (final story objects). Returns story id (bigint).
ID generation matches news_articles: deterministic string ID -> bigint via MD5 (first 7 bytes, mod max_bigint).
"""
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from supabase import Client

from backend.storage.news_articles_save import _string_id_to_bigint

logger = logging.getLogger(__name__)


def story_string_id(asof_date: date, ticker: Optional[str], seed: str) -> str:
    """Stable string ID for a story row (same inputs -> same id, like news_articles)."""
    d = asof_date.isoformat() if hasattr(asof_date, "isoformat") else str(asof_date)[:10]
    t = (ticker or "").strip() or ""
    return f"story_{d}_{t}_{seed}"


def insert_story(
    supabase: Client,
    asof_date: date,
    story_payload: Dict[str, Any],
    ticker: Optional[str] = None,
    cluster_type: Optional[str] = None,
    cluster_size: Optional[int] = None,
    pipeline_version: Optional[str] = None,
    llm_model: Optional[str] = None,
    prompt_version: Optional[str] = None,
    seed: Optional[str] = None,
    embedding: Optional[List[float]] = None,
) -> Optional[int]:
    """
    Insert one row into story. story_payload = output from story_llm (normalized dict).
    seed: deterministic cluster key (e.g. sorted article ids) so same cluster -> same story id.
    embedding: optional vector (e.g. from title+topics+summary) for long-story similarity; stored when provided.
    Returns story id (bigint) or None on failure. ID generated like news_articles (string -> bigint).
    """
    if not seed:
        seed = story_payload.get("title") or ""
        if not seed:
            seed = str(cluster_size or 0)
    string_id = story_string_id(asof_date, ticker, seed)
    story_id = _string_id_to_bigint(string_id)
    row = {
        "id": story_id,
        "asof_date": asof_date.isoformat(),
        "ticker": (ticker or story_payload.get("ticker") or "").strip() or None,
        "title": story_payload.get("title") or "",
        "summary": story_payload.get("summary") or "",
        "topics": story_payload.get("topics") or [],
        "session_label": story_payload.get("session_label") or "UNKNOWN",
        "session_confidence": story_payload.get("session_confidence"),
        "event_time_evidence": story_payload.get("event_time_evidence") or [],
        "risk_horizon": story_payload.get("risk_horizon"),
        "prob_move_ge_1pct": story_payload.get("prob_move_ge_1pct"),
        "prob_move_ge_2pct": story_payload.get("prob_move_ge_2pct"),
        "expected_abs_move_pct": story_payload.get("expected_abs_move_pct"),
        "direction_bias": story_payload.get("direction_bias") or "NEUTRAL",
        "risk_confidence": story_payload.get("risk_confidence"),
        "risk_drivers": story_payload.get("risk_drivers") or [],
        "risk_caveats": story_payload.get("risk_caveats") or [],
        "is_filing_related": story_payload.get("is_filing_related") or False,
        "filing_form_types": story_payload.get("filing_form_types") or [],
        "estimated_filing_date_et": story_payload.get("estimated_filing_date_et"),
        "filing_signals": story_payload.get("filing_signals") or [],
        "pipeline_version": pipeline_version,
        "llm_model": llm_model,
        "prompt_version": prompt_version,
        "cluster_type": cluster_type,
        "cluster_size": cluster_size,
    }
    if embedding is not None:
        row["embedding"] = embedding
    try:
        supabase.table("story").insert(row).execute()
        return story_id
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "unique" in err or "conflict" in err:
            return story_id
        logger.warning("insert_story failed: %s", e)
        return None
