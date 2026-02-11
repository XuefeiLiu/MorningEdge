"""
Query operations for macro_daily_briefs table (one analyst report per topic per day).
"""
import logging
from datetime import date, datetime, timezone
from typing import List, Dict, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_briefs_for_date(
    supabase: Client,
    as_of_date: date,
    topic: Optional[str] = None,
) -> List[Dict]:
    """
    Get macro daily briefs for a date (all 8 topics or filter by topic).
    """
    if not supabase:
        supabase = get_supabase_client()
    try:
        query = (
            supabase.table("macro_daily_briefs")
            .select("*")
            .eq("as_of_date", as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10])
        )
        if topic:
            query = query.eq("topic", topic)
        query = query.order("topic")
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error querying macro_daily_briefs: {e}")
        return []


def get_brief_by_date_and_topic(
    supabase: Client,
    as_of_date: date,
    topic: str,
) -> Optional[Dict]:
    """Get a single brief for date + topic."""
    briefs = get_briefs_for_date(supabase, as_of_date, topic=topic)
    return briefs[0] if briefs else None
