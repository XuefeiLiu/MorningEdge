"""
Shared helper functions used across routers.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo


def ensure_tz(dt: Any) -> Optional[datetime]:
    """Normalize value to timezone-aware datetime for comparison. Returns None if unparseable."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        d = dt
    else:
        try:
            s = str(dt).strip()[:30]
            s = s.replace("Z", "+00:00")
            d = datetime.fromisoformat(s)
        except (ValueError, TypeError):
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def parse_datetime_param(s: Optional[str]) -> Optional[datetime]:
    """Parse ISO8601 string to datetime for range filtering. Ensures timezone-aware (UTC)."""
    if not s or not isinstance(s, str):
        return None
    s = str(s).strip()[:30]
    if not s:
        return None
    try:
        dt_str = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def parse_latest_from_event_time_evidence(evidence: Any) -> Optional[datetime]:
    """
    Parse event_time_evidence (array of strings, each entry like "published_at=2026-02-05T18:30:00Z").
    Returns the latest UTC datetime. None if evidence is empty or no parseable datetime found.
    """
    if not evidence or not isinstance(evidence, list):
        return None
    parsed: List[datetime] = []
    for item in evidence:
        if not item or not isinstance(item, str):
            continue
        s = str(item).strip()
        if not s:
            continue
        if "published_at=" in s:
            s = s.split("published_at=", 1)[1].strip()
        if not s:
            continue
        try:
            dt_str = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed.append(dt)
        except (ValueError, TypeError, OverflowError):
            try:
                from dateutil.parser import parse as dateutil_parse
                dt = dateutil_parse(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                parsed.append(dt)
            except (ValueError, TypeError, OverflowError):
                continue
    if not parsed:
        return None
    return max(parsed)


def filing_display_title(form_type: Optional[str], filed_date: Optional[str], fiscal_year: Optional[int], period: Optional[str]) -> str:
    """Human-readable filing name, e.g. '10-Q · Q3 2024' or '10-K · FY 2024'."""
    form = (form_type or "").strip() or "Filing"
    if fiscal_year is not None and period:
        return f"{form} · {period} {fiscal_year}"
    if filed_date:
        year = str(filed_date)[:4] if len(str(filed_date)) >= 4 else ""
        return f"{form} · {year}" if year else form
    return form


def looks_like_table(text: str) -> bool:
    """Heuristic: multiple lines with consistent pipe/tab separators suggest a table."""
    if not text or len(text.strip()) < 20:
        return False
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    if len(lines) < 2:
        return False
    pipe_counts = [ln.count("|") for ln in lines]
    if min(pipe_counts) >= 2 and max(pipe_counts) == min(pipe_counts) and len(set(pipe_counts)) == 1:
        return True
    tab_counts = [ln.count("\t") for ln in lines]
    if min(tab_counts) >= 1 and len([c for c in tab_counts if c > 0]) >= len(lines) - 1:
        return True
    return False


def impact_score_to_level(score: Optional[float]) -> str:
    """Derive display level from impact_score (0–1). Null -> medium."""
    if score is None:
        return "medium"
    if score >= 0.7:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


def sort_key_impact_score(item: Dict[str, Any]) -> Tuple[bool, float]:
    """Sort key: (nulls last, -score) so higher score first, nulls last."""
    s = item.get("impact_score")
    if s is None:
        return (True, 0.0)
    try:
        return (False, -float(s))
    except (TypeError, ValueError):
        return (True, 0.0)


def get_overnight_window_ny() -> Tuple[datetime, datetime]:
    """Return (start, end) for the overnight session in UTC. Start = 4pm ET on the most recent US business day."""
    from backend.utils.us_business_day import is_us_business_day
    NY = ZoneInfo("America/New_York")
    now_utc = datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY)
    ref_date = now_ny.date() if now_ny.hour >= 16 else (now_ny - timedelta(days=1)).date()
    while not is_us_business_day(ref_date):
        ref_date -= timedelta(days=1)
    start_ny = datetime(ref_date.year, ref_date.month, ref_date.day, 16, 0, 0, 0, tzinfo=NY)
    start_utc = start_ny.astimezone(timezone.utc)
    return start_utc, now_utc
