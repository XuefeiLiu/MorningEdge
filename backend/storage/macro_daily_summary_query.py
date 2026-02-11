"""
Query operations for macro_daily_summary (one row per date).
"""
import logging
from datetime import date
from typing import Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_daily_summary_for_date(
    supabase: Optional[Client] = None,
    as_of_date: Optional[date] = None,
) -> Optional[dict]:
    """
    Get the macro daily summary for a date. Returns dict with title, summary, summary_bullets, as_of_date, etc.
    """
    if not supabase:
        supabase = get_supabase_client()
    date_str = (as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]) if as_of_date else None
    if not date_str:
        return None
    try:
        r = supabase.table("macro_daily_summary").select("*").eq("as_of_date", date_str).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error("Error querying macro_daily_summary: %s", e)
        return None
