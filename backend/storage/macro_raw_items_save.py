"""
Save operations for macro_raw_items table (traceability for raw macro news).
ID: application supplies id via _string_id_to_bigint(macro_raw_string_id(url, published_at)).
"""
import logging
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.macro_id_utils import _string_id_to_bigint, macro_raw_string_id

logger = logging.getLogger(__name__)


def _ensure_tz(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def save_raw_items(
    supabase: Client,
    items: List[Dict[str, Any]],
    as_of_date: date,
    collector: str,
) -> int:
    """
    Insert macro raw items. Skips duplicates (by url or by id).
    Each item should have: title, summary, url, source, published_at, topic_candidate, topic, relevance_score, region.
    """
    if not supabase:
        supabase = get_supabase_client()
    inserted = 0
    for item in items:
        try:
            url = item.get("url") or ""
            published_at = item.get("published_at")
            pub_iso = _ensure_tz(published_at) if published_at else ""
            string_id = macro_raw_string_id(url, pub_iso)
            db_id = _string_id_to_bigint(string_id)
            row = {
                "id": db_id,
                "as_of_date": as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10],
                "title": item.get("title"),
                "summary": item.get("summary"),
                "url": url or None,
                "source": item.get("source"),
                "published_at": _ensure_tz(published_at),
                "collector": item.get("collector", collector),
                "topic_candidate": item.get("topic_candidate"),
                "topic": item.get("topic"),
                "relevance_score": item.get("relevance_score"),
                "region": item.get("region"),
            }
            supabase.table("macro_raw_items").upsert(row, on_conflict="id").execute()
            inserted += 1
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                continue
            logger.warning(f"Failed to save macro raw item: {e}")
    logger.info(f"Saved {inserted} macro raw items for {as_of_date}")
    return inserted
