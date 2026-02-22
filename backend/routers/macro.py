"""Macro briefs, daily summary, and impact endpoints."""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/macro/briefs", tags=["Macro"])
async def get_macro_briefs(
    date_param: Optional[str] = Query(None, alias="date", description="Date in YYYY-MM-DD format"),
    topic: Optional[str] = Query(None, description="Optional topic filter (e.g. FX, RATE, Fiscal Policy)"),
    range_param: Optional[str] = Query(None, alias="range", description="Set to 'week' with topic for past 7 days"),
):
    """Get macro briefs. With date only: list of briefs. With date+topic: single full brief. With topic+range=week: past 7 days."""
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.macro_brief_by_asset_query import (
        get_all_briefs_for_date, get_brief_by_date_and_topic, get_briefs_for_topic_in_range,
    )
    supabase = get_supabase_client()
    if range_param == "week" and topic is not None:
        end_date = date.today()
        start_date = end_date - timedelta(days=6)
        return get_briefs_for_topic_in_range(supabase, topic, start_date, end_date)
    if date_param is None:
        raise HTTPException(status_code=400, detail="date required unless topic and range=week")
    try:
        as_of_date = date.fromisoformat(date_param)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")
    if topic is not None:
        brief = get_brief_by_date_and_topic(supabase, as_of_date, topic)
        if not brief:
            raise HTTPException(status_code=404, detail=f"No brief for topic '{topic}' on {date_param}")
        from backend.macro.article_format import build_article_bullets
        brief = dict(brief)
        brief["article_bullets"] = build_article_bullets(brief)
        return brief
    return get_all_briefs_for_date(supabase, as_of_date, topic=None, full=False)


@router.get("/macro/daily-summary", tags=["Macro"])
async def get_macro_daily_summary(
    date_param: Optional[str] = Query(None, alias="date", description="Date in YYYY-MM-DD format"),
):
    """Get the daily macro summary for a date (LLM-synthesized from all 8 topic briefs)."""
    if not date_param:
        raise HTTPException(status_code=400, detail="date required (YYYY-MM-DD)")
    try:
        as_of_date = date.fromisoformat(date_param)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.macro_daily_summary_query import get_daily_summary_for_date
    supabase = get_supabase_client()
    row = get_daily_summary_for_date(supabase, as_of_date)
    if not row:
        raise HTTPException(status_code=404, detail=f"No daily summary for {date_param}")
    return row


@router.get("/macro/daily", tags=["Macro"])
async def get_macro_daily(
    date_str: str = Query(..., alias="date", description="Date YYYY-MM-DD"),
    full: bool = Query(False, description="Return full report"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
):
    """Get daily macro topic briefs for a date."""
    from backend.storage.macro_brief_by_asset_query import get_all_briefs_for_date
    from backend.storage.supabase_client import get_supabase_client
    try:
        as_of = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")
    supabase = get_supabase_client()
    briefs = get_all_briefs_for_date(supabase, as_of, topic=topic, full=full)
    return {"date": date_str[:10], "briefs": briefs or []}


@router.get("/macro/daily/{date}/impact", tags=["Macro"])
async def get_macro_daily_impact(
    date: str,
    portfolio_id: Optional[str] = Query(None, description="Portfolio id"),
):
    """Get macro daily impact report for a date."""
    from backend.storage.macro_impact_reports_query import get_impact_for_date
    from backend.storage.supabase_client import get_supabase_client
    try:
        as_of = datetime.strptime(date.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")
    supabase = get_supabase_client()
    report = get_impact_for_date(supabase, as_of_date=as_of, portfolio_id=portfolio_id)
    if not report:
        raise HTTPException(status_code=404, detail="No impact report for this date")
    return report


@router.post("/macro/daily/{date}/impact", tags=["Macro"])
async def post_macro_daily_impact(date: str, request: Request):
    """Generate (and cache) macro daily impact report for a date."""
    from backend.macro.impact import generate_impact_report
    from backend.storage.macro_impact_reports_query import get_impact_for_date
    from backend.storage.supabase_client import get_supabase_client
    try:
        as_of = datetime.strptime(date.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")
    try:
        body = await request.json()
    except Exception:
        body = {}
    portfolio = body.get("portfolio") if isinstance(body, dict) else None
    portfolio_id = body.get("portfolio_id") if isinstance(body, dict) else None
    supabase = get_supabase_client()
    try:
        report_id = await generate_impact_report(
            as_of, supabase=supabase, portfolio=portfolio, portfolio_id=portfolio_id
        )
    except Exception as e:
        logger.exception("Impact generation failed: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
    if report_id is None:
        raise HTTPException(status_code=502, detail="Impact report generation returned no id")
    report = get_impact_for_date(supabase, as_of_date=as_of, portfolio_id=portfolio_id)
    return report or {"id": report_id}
