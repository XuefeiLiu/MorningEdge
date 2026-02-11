"""
Query operations for macro_raw_items table.
"""
import logging
from datetime import date
from typing import List, Dict, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_raw_items_for_date(
    supabase: Optional[Client],
    as_of_date: date,
    topic: Optional[str] = None,
    limit: Optional[int] = None,
    min_relevance: Optional[int] = None,
) -> List[Dict]:
    """Get macro raw items for a date (optionally filter by topic, min_relevance). Ordered by relevance_score desc."""
    if not supabase:
        supabase = get_supabase_client()
    date_str = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    try:
        query = (
            supabase.table("macro_raw_items")
            .select("*")
            .eq("as_of_date", date_str)
        )
        if topic:
            query = query.eq("topic", topic)
        if min_relevance is not None and min_relevance > 0:
            query = query.gte("relevance_score", min_relevance)
        query = query.order("relevance_score", desc=True)
        if limit:
            query = query.limit(limit)
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error("Error querying macro_raw_items: %s", e)
        return []


def get_raw_items_for_date_primary_plus_cross(
    supabase: Optional[Client],
    as_of_date: date,
    primary_topic: str,
    primary_limit: int = 20,
    cross_limit_per_topic: int = 3,
    min_relevance: Optional[int] = None,
) -> List[Dict]:
    """
    Get raw items for date: primary_topic items first (up to primary_limit), then up to
    cross_limit_per_topic items from each other topic for cross-impact. Order: primary first, then others by topic.
    If min_relevance is set, only items with relevance_score >= min_relevance are returned (reduces noise).
    """
    if not supabase:
        supabase = get_supabase_client()
    from backend.config import MACRO_TOPICS
    out: List[Dict] = []
    primary = get_raw_items_for_date(supabase, as_of_date, topic=primary_topic, limit=primary_limit, min_relevance=min_relevance)
    out.extend(primary)
    for t in MACRO_TOPICS:
        if t == primary_topic:
            continue
        others = get_raw_items_for_date(supabase, as_of_date, topic=t, limit=cross_limit_per_topic, min_relevance=min_relevance)
        out.extend(others)
    return out
