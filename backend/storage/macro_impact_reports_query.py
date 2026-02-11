"""
Query operations for macro_daily_impact_reports (on-demand portfolio impact per date).
"""
import logging
from datetime import date
from typing import Dict, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def get_impact_for_date(
    supabase: Optional[Client] = None,
    as_of_date: Optional[date] = None,
    portfolio_id: Optional[str] = None,
) -> Optional[Dict]:
    """
    Get the macro daily impact report for a date (and optional portfolio_id).
    Returns report_markdown, signals, factor_mapping, factor_impacts, topics, etc.
    """
    if not supabase:
        supabase = get_supabase_client()
    date_str = (as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]) if as_of_date else None
    if not date_str:
        return None
    try:
        pid = (portfolio_id or "default").strip() or "default"
        query = supabase.table("macro_daily_impact_reports").select("*").eq("as_of_date", date_str)
        if pid == "default":
            query = query.or_("portfolio_id.is.null,portfolio_id.eq.default")
        else:
            query = query.eq("portfolio_id", pid)
        result = query.limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error querying macro_daily_impact_reports: {e}")
        return None
