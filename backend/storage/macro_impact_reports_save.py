"""
Save operations for macro_daily_impact_reports (on-demand portfolio impact per date).
ID: application supplies id via _string_id_to_bigint(macro_impact_string_id(as_of_date, portfolio_id)).
Unique index is on (as_of_date, COALESCE(portfolio_id, 'default')); we do select-then-update-or-insert.
"""
import logging
from datetime import date
from typing import Dict, Any, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.macro_id_utils import _string_id_to_bigint, macro_impact_string_id
from backend.storage.macro_impact_reports_query import get_impact_for_date

logger = logging.getLogger(__name__)


def save_impact_report(
    supabase: Optional[Client],
    as_of_date: date,
    payload: Dict[str, Any],
    portfolio_id: Optional[str] = None,
) -> Optional[int]:
    """
    Insert or update one macro daily impact report for (as_of_date, portfolio_id).
    payload: topics, report_markdown, signals, factor_mapping, factor_impacts.
    """
    if not supabase:
        supabase = get_supabase_client()
    pid = (portfolio_id or "default").strip() or "default"
    string_id = macro_impact_string_id(as_of_date, pid)
    db_id = _string_id_to_bigint(string_id)
    date_str = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    row = {
        "id": db_id,
        "as_of_date": date_str,
        "portfolio_id": None if pid == "default" else pid,
        "topics": payload.get("topics"),
        "report_markdown": payload.get("report_markdown"),
        "signals": payload.get("signals"),
        "factor_mapping": payload.get("factor_mapping"),
        "factor_impacts": payload.get("factor_impacts"),
    }
    try:
        existing = get_impact_for_date(supabase=supabase, as_of_date=as_of_date, portfolio_id=portfolio_id)
        if existing:
            supabase.table("macro_daily_impact_reports").update(
                {
                    "topics": row["topics"],
                    "report_markdown": row["report_markdown"],
                    "signals": row["signals"],
                    "factor_mapping": row["factor_mapping"],
                    "factor_impacts": row["factor_impacts"],
                }
            ).eq("id", existing["id"]).execute()
        else:
            supabase.table("macro_daily_impact_reports").insert(row).execute()
        return db_id
    except Exception as e:
        logger.error(f"Failed to save macro_daily_impact_report {date_str} portfolio={pid}: {e}")
        return None
