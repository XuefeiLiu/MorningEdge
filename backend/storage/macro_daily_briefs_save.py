"""
Save operations for macro_daily_briefs table (one analyst report per topic per day).
ID: application supplies id via _string_id_to_bigint(macro_brief_string_id(as_of_date, topic)).
"""
import logging
from datetime import date
from typing import Dict, Any, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.macro_id_utils import _string_id_to_bigint, macro_brief_string_id

logger = logging.getLogger(__name__)


def _topic_slug(topic: str) -> str:
    return (topic or "").replace(" ", "_").strip() or "unknown"


def save_brief(
    supabase: Client,
    as_of_date: date,
    topic: str,
    payload: Dict[str, Any],
) -> Optional[int]:
    """
    Upsert one macro daily brief for (as_of_date, topic).
    payload: title, summary, summary_bullets, delta_vs_yday, why_it_matters, sources, coverage_gap, mechanism, transmission, relative_value.
    """
    if not supabase:
        supabase = get_supabase_client()
    slug = _topic_slug(topic)
    string_id = macro_brief_string_id(as_of_date, slug)
    db_id = _string_id_to_bigint(string_id)
    date_str = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    row = {
        "id": db_id,
        "as_of_date": date_str,
        "topic": topic.strip(),
        "title": payload.get("title", ""),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
        "delta_vs_yday": payload.get("delta_vs_yday"),
        "why_it_matters": payload.get("why_it_matters"),
        "sources": payload.get("sources"),
        "coverage_gap": bool(payload.get("coverage_gap", False)),
        "mechanism": payload.get("mechanism"),
        "transmission": payload.get("transmission"),
        "relative_value": payload.get("relative_value"),
    }
    try:
        supabase.table("macro_daily_briefs").upsert(row, on_conflict="as_of_date,topic").execute()
        return db_id
    except Exception as e:
        logger.error(f"Failed to save macro_daily_brief {date_str} {topic}: {e}")
        return None


def save_briefs_for_date(
    supabase: Client,
    as_of_date: date,
    briefs: list[Dict[str, Any]],
) -> int:
    """Save multiple briefs for a date (one per topic). briefs = list of {topic, ...payload}."""
    count = 0
    for b in briefs:
        topic = b.get("topic")
        if not topic:
            continue
        if save_brief(supabase, as_of_date, topic, b) is not None:
            count += 1
    return count
