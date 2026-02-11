"""
Query operations for per-asset macro brief tables (macro_brief_fx, rates, credit, commodity, equity, policy).
Unified get_all_briefs_for_date returns 8 briefs (5 asset + 3 policy) with topic field for API compatibility.
"""
import logging
from datetime import date
from typing import List, Dict, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# Topic labels for API (order: FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy, Monetary Policy, Trump)
ASSET_TOPIC_ORDER = ["FX", "RATE", "CREDIT", "COMMODITY", "EQUITY"]
POLICY_TOPICS = ["Fiscal Policy", "Monetary Policy", "Trump"]


def _date_str(d: date) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]


def get_brief_fx(supabase: Client, as_of_date: date) -> Optional[Dict]:
    """Get macro_brief_fx row for date. Returns dict with topic='FX' added."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_brief_fx").select("*").eq("as_of_date", _date_str(as_of_date)).limit(1).execute()
        row = r.data[0] if r.data else None
        if row:
            row["topic"] = "FX"
        return row
    except Exception as e:
        logger.error("Error querying macro_brief_fx: %s", e)
        return None


def get_brief_rates(supabase: Client, as_of_date: date) -> Optional[Dict]:
    """Get macro_brief_rates row for date. Returns dict with topic='RATE' added."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_brief_rates").select("*").eq("as_of_date", _date_str(as_of_date)).limit(1).execute()
        row = r.data[0] if r.data else None
        if row:
            row["topic"] = "RATE"
        return row
    except Exception as e:
        logger.error("Error querying macro_brief_rates: %s", e)
        return None


def get_brief_credit(supabase: Client, as_of_date: date) -> Optional[Dict]:
    """Get macro_brief_credit row for date. Returns dict with topic='CREDIT' added."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_brief_credit").select("*").eq("as_of_date", _date_str(as_of_date)).limit(1).execute()
        row = r.data[0] if r.data else None
        if row:
            row["topic"] = "CREDIT"
        return row
    except Exception as e:
        logger.error("Error querying macro_brief_credit: %s", e)
        return None


def get_brief_commodity(supabase: Client, as_of_date: date) -> Optional[Dict]:
    """Get macro_brief_commodity row for date. Returns dict with topic='COMMODITY' added."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_brief_commodity").select("*").eq("as_of_date", _date_str(as_of_date)).limit(1).execute()
        row = r.data[0] if r.data else None
        if row:
            row["topic"] = "COMMODITY"
        return row
    except Exception as e:
        logger.error("Error querying macro_brief_commodity: %s", e)
        return None


def get_brief_equity(supabase: Client, as_of_date: date) -> Optional[Dict]:
    """Get macro_brief_equity row for date. Returns dict with topic='EQUITY' added."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_brief_equity").select("*").eq("as_of_date", _date_str(as_of_date)).limit(1).execute()
        row = r.data[0] if r.data else None
        if row:
            row["topic"] = "EQUITY"
        return row
    except Exception as e:
        logger.error("Error querying macro_brief_equity: %s", e)
        return None


def get_briefs_policy(supabase: Client, as_of_date: date) -> List[Dict]:
    """Get macro_brief_policy rows for date (up to 3: Fiscal Policy, Monetary Policy, Trump). Each row has topic set."""
    if not supabase:
        supabase = get_supabase_client()
    try:
        r = supabase.table("macro_brief_policy").select("*").eq("as_of_date", _date_str(as_of_date)).execute()
        return list(r.data) if r.data else []
    except Exception as e:
        logger.error("Error querying macro_brief_policy: %s", e)
        return []


def get_all_briefs_for_date(
    supabase: Optional[Client],
    as_of_date: date,
    topic: Optional[str] = None,
    full: bool = True,
) -> List[Dict]:
    """
    Get all 8 macro briefs for a date from per-asset tables (5 asset + 3 policy).
    Returns list of briefs with topic field; order: FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy, Monetary Policy, Trump.
    If topic is set, return only that brief (if present). If full=False, strip asset-specific columns for list view (title, summary, topic).
    """
    if not supabase:
        supabase = get_supabase_client()
    briefs: List[Dict] = []
    asset_getters = [
        ("FX", get_brief_fx),
        ("RATE", get_brief_rates),
        ("CREDIT", get_brief_credit),
        ("COMMODITY", get_brief_commodity),
        ("EQUITY", get_brief_equity),
    ]
    for top, getter in asset_getters:
        if topic and topic != top:
            continue
        row = getter(supabase, as_of_date)
        if row:
            briefs.append(row)
    if not topic or topic in POLICY_TOPICS:
        for row in get_briefs_policy(supabase, as_of_date):
            if topic and row.get("topic") != topic:
                continue
            briefs.append(row)
    # Sort so policy topics are in order Fiscal Policy, Monetary Policy, Trump
    def sort_key(b: Dict) -> tuple:
        t = b.get("topic") or ""
        if t in ASSET_TOPIC_ORDER:
            return (0, ASSET_TOPIC_ORDER.index(t))
        return (1, POLICY_TOPICS.index(t) if t in POLICY_TOPICS else 99)
    briefs.sort(key=sort_key)
    if not full:
        # List view: only topic, title, summary
        briefs = [{"topic": b.get("topic"), "title": b.get("title"), "summary": b.get("summary")} for b in briefs]
    return briefs


def get_brief_by_date_and_topic(
    supabase: Optional[Client],
    as_of_date: date,
    topic: str,
) -> Optional[Dict]:
    """Get a single brief for date + topic from per-asset tables."""
    briefs = get_all_briefs_for_date(supabase, as_of_date, topic=topic, full=True)
    return briefs[0] if briefs else None


# Topic -> (table name, is_policy)
_ASSET_TABLE_BY_TOPIC: Dict[str, tuple] = {
    "FX": ("macro_brief_fx", False),
    "RATE": ("macro_brief_rates", False),
    "CREDIT": ("macro_brief_credit", False),
    "COMMODITY": ("macro_brief_commodity", False),
    "EQUITY": ("macro_brief_equity", False),
    "Fiscal Policy": ("macro_brief_policy", True),
    "Monetary Policy": ("macro_brief_policy", True),
    "Trump": ("macro_brief_policy", True),
}


def get_briefs_for_topic_in_range(
    supabase: Optional[Client],
    topic: str,
    start_date: date,
    end_date: date,
) -> List[Dict]:
    """
    Get briefs for one topic over a date range. Returns list of dicts with at least
    as_of_date, title, summary, topic; ordered by as_of_date desc.
    """
    if not supabase:
        supabase = get_supabase_client()
    entry = _ASSET_TABLE_BY_TOPIC.get(topic)
    if not entry:
        return []
    table_name, is_policy = entry
    start_s = _date_str(start_date)
    end_s = _date_str(end_date)
    try:
        q = (
            supabase.table(table_name)
            .select("as_of_date, title, summary, coverage_gap")
            .gte("as_of_date", start_s)
            .lte("as_of_date", end_s)
            .order("as_of_date", desc=True)
        )
        if is_policy:
            q = q.eq("topic", topic)
        r = q.execute()
        rows = list(r.data) if r.data else []
        for row in rows:
            row["topic"] = topic
        return rows
    except Exception as e:
        logger.error("Error querying %s for topic %s in range: %s", table_name, topic, e)
        return []
