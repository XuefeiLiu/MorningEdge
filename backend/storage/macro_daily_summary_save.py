"""
Save operations for macro_daily_summary (one row per date; summary of all 8 topic briefs).
ID: application supplies id via _string_id_to_bigint(macro_daily_summary_string_id(as_of_date)).
Unique on as_of_date; upsert by as_of_date.
"""
import logging
from datetime import date
from typing import Dict, Any, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.macro_id_utils import _string_id_to_bigint, macro_daily_summary_string_id

logger = logging.getLogger(__name__)


def save_daily_summary(
    supabase: Optional[Client],
    as_of_date: date,
    payload: Dict[str, Any],
) -> Optional[int]:
    """
    Insert or upsert one macro_daily_summary row for as_of_date.
    payload: title, summary, summary_bullets.
    """
    if not supabase:
        supabase = get_supabase_client()
    string_id = macro_daily_summary_string_id(as_of_date)
    db_id = _string_id_to_bigint(string_id)
    date_str = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    row = {
        "id": db_id,
        "as_of_date": date_str,
        "title": payload.get("title"),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
    }
    try:
        supabase.table("macro_daily_summary").upsert(row, on_conflict="as_of_date").execute()
        return db_id
    except Exception as e:
        logger.error("Failed to save macro_daily_summary %s: %s", date_str, e)
        return None
