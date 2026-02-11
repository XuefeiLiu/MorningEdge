"""
Morning Edge - Pre-Market Briefing System
FastAPI Backend Application
"""
import logging
import os
import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.models import (
    WatchlistUpdateRequest, WatchlistResponse, BriefingReport,
    AISummaryRequest, AISummaryResponse, HealthResponse,
    FilterSettingsRequest, Price5MinItem
)
from backend.storage.watchlist_manager import watchlist_manager
from backend.utils.us_business_day import is_us_business_day
from backend.services.briefing import briefing_generator
from backend.services.ai_summaries import ai_summary_generator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Morning Edge Pre-Market Briefing System starting up")
    yield
    logger.info("Shutting down")


# Create FastAPI app
app = FastAPI(
    title="Morning Edge",
    description="US Stock Pre-Market Briefing System",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for frontend (default: localhost; set CORS_ORIGINS for production, comma-separated)
# Browser sends Origin without trailing slash; allowed origins must match exactly (e.g. https://your-app.vercel.app).
_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_cors_origins_str = os.environ.get("CORS_ORIGINS", "").strip()
allow_origins = _default_origins if not _cors_origins_str else [o.strip().rstrip("/") for o in _cors_origins_str.split(",") if o.strip()]
logger.info("CORS allowed_origins: %s", allow_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== Macro Briefs ==============

@app.get("/macro/briefs", tags=["Macro"])
async def get_macro_briefs(
    date_param: Optional[str] = Query(None, alias="date", description="Date in YYYY-MM-DD format"),
    topic: Optional[str] = Query(None, description="Optional topic filter (e.g. FX, RATE, Fiscal Policy)"),
    range_param: Optional[str] = Query(None, alias="range", description="Set to 'week' with topic for past 7 days"),
):
    """
    Get macro briefs. With date only: list of briefs (topic, title, summary).
    With date and topic: single full brief or 404.
    With topic and range=week (date optional): list of briefs for that topic over past 7 days, ordered by date desc.
    """
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.macro_brief_by_asset_query import (
        get_all_briefs_for_date,
        get_brief_by_date_and_topic,
        get_briefs_for_topic_in_range,
    )

    supabase = get_supabase_client()

    if range_param == "week" and topic is not None:
        end_date = date.today()
        start_date = end_date - timedelta(days=6)
        briefs = get_briefs_for_topic_in_range(supabase, topic, start_date, end_date)
        return briefs

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
    briefs = get_all_briefs_for_date(supabase, as_of_date, topic=None, full=False)
    return briefs


@app.get("/macro/daily-summary", tags=["Macro"])
async def get_macro_daily_summary(
    date_param: Optional[str] = Query(None, alias="date", description="Date in YYYY-MM-DD format"),
):
    """
    Get the daily macro summary of summaries for a date (LLM-synthesized from all 8 topic briefs).
    Returns title, summary, summary_bullets, as_of_date. 404 if no row for that date.
    """
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


# ============== Health Check ==============

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check system health and status."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="1.0.0"
    )


# ============== Overnight Window (early registration) ==============

class OvernightWindowResponse(BaseModel):
    """Overnight window boundaries: start = most recent business day 4pm NY, end = now. ISO8601 UTC strings."""
    start: str
    end: str


def _get_overnight_window_ny() -> Tuple[datetime, datetime]:
    """Return (start, end) for the overnight session in UTC. Start = 4pm ET on the most recent US business day."""
    NY = ZoneInfo("America/New_York")
    now_utc = datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY)
    ref_date = now_ny.date() if now_ny.hour >= 16 else (now_ny - timedelta(days=1)).date()
    while not is_us_business_day(ref_date):
        ref_date -= timedelta(days=1)
    start_ny = datetime(ref_date.year, ref_date.month, ref_date.day, 16, 0, 0, 0, tzinfo=NY)
    start_utc = start_ny.astimezone(timezone.utc)
    return start_utc, now_utc


@app.get("/overnight-window", response_model=OvernightWindowResponse, tags=["Overnight Stories"])
async def get_overnight_window():
    """Return the current overnight session boundaries (most recent business day 4pm NY to now) for High-Impact Overnight and Market Prediction."""
    start_utc, end_utc = _get_overnight_window_ny()
    return OvernightWindowResponse(start=start_utc.isoformat(), end=end_utc.isoformat())


# ============== Watchlist Management ==============

@app.get("/watchlist", response_model=WatchlistResponse, tags=["Watchlist"])
async def get_watchlist():
    """Get the current watchlist of stock symbols."""
    symbols = watchlist_manager.get_symbols()
    updated_at = watchlist_manager.get_updated_at() or datetime.utcnow()
    
    return WatchlistResponse(
        symbols=symbols,
        updated_at=updated_at
    )


@app.put("/watchlist", response_model=WatchlistResponse, tags=["Watchlist"])
async def update_watchlist(request: WatchlistUpdateRequest):
    """
    Update the watchlist with a new set of symbols.
    Replaces the existing watchlist.
    """
    if not request.symbols:
        raise HTTPException(status_code=400, detail="Symbols list cannot be empty")
    
    # Validate symbols (basic check)
    for symbol in request.symbols:
        if not symbol.strip() or len(symbol) > 10:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid symbol: {symbol}"
            )
    
    result = watchlist_manager.set_symbols(request.symbols)
    
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )


@app.post("/watchlist/add", response_model=WatchlistResponse, tags=["Watchlist"])
async def add_symbol(symbol: str = Query(..., description="Stock symbol to add")):
    """Add a single symbol to the watchlist."""
    if not symbol.strip() or len(symbol) > 10:
        raise HTTPException(status_code=400, detail=f"Invalid symbol: {symbol}")
    
    result = watchlist_manager.add_symbol(symbol)
    
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )


@app.delete("/watchlist/{symbol}", response_model=WatchlistResponse, tags=["Watchlist"])
async def remove_symbol(symbol: str):
    """Remove a symbol from the watchlist."""
    result = watchlist_manager.remove_symbol(symbol)
    
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )


@app.delete("/watchlist", response_model=WatchlistResponse, tags=["Watchlist"])
async def clear_watchlist():
    """Clear all symbols from the watchlist."""
    result = watchlist_manager.clear()
    
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )


# ============== Briefing Generation ==============

@app.get("/briefing", response_model=BriefingReport, tags=["Briefing"])
async def get_briefing(
    start_time: Optional[datetime] = Query(
        None,
        description="Start of data collection window (defaults to last market close)"
    ),
    end_time: Optional[datetime] = Query(
        None,
        description="End of data collection window (defaults to now)"
    ),
    use_mock: bool = Query(
        False,
        description="Force use of mock data"
    )
):
    """
    Generate a pre-market briefing report for the current watchlist.
    
    The report includes:
    - Company news filtered by relevance
    - Macroeconomic events
    - Technical data (prices, support/resistance)
    - Market sentiment
    - SEC filings
    - Per-stock impact summaries with trading direction
    - Risk warnings
    """
    symbols = watchlist_manager.get_symbols()
    
    if not symbols:
        raise HTTPException(
            status_code=400,
            detail="Watchlist is empty. Add symbols first."
        )
    
    try:
        report = await briefing_generator.generate(
            symbols=symbols,
            start_time=start_time,
            end_time=end_time,
            use_mock=use_mock
        )
        return report
    except asyncio.CancelledError as ce:
        logger.error(f"Request was cancelled: {ce}")
        raise HTTPException(status_code=499, detail="Request was cancelled by client")
    except Exception as e:
        logger.error(f"Error generating briefing: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate briefing: {str(e)}"
        )


@app.get("/briefing/stock/{symbol}", tags=["Briefing"])
async def get_stock_briefing(
    symbol: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    use_mock: bool = False
):
    """
    Generate a briefing report for a single stock.
    The stock is temporarily added to the analysis if not in watchlist.
    """
    try:
        report = await briefing_generator.generate(
            symbols=[symbol.upper()],
            start_time=start_time,
            end_time=end_time,
            use_mock=use_mock
        )
        
        # Return just the stock summary
        if report.stock_summaries:
            return {
                "symbol": symbol.upper(),
                "summary": report.stock_summaries[0],
                "news": [n for n in report.company_news if symbol.upper() == n.ticker.upper()],
                "filings": [f for f in report.sec_filings if f.symbol == symbol.upper()],
                "macro_events": report.macro_events,
                "risk_warnings": report.risk_warnings
            }
        
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating stock briefing for {symbol}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate briefing: {str(e)}"
        )


# ============== AI Summaries ==============

@app.post("/ai/summarize", response_model=AISummaryResponse, tags=["AI"])
async def generate_ai_summary(request: AISummaryRequest):
    """
    Generate an AI-powered summary of provided items.
    Falls back to rule-based summary if OpenAI is unavailable.
    """
    try:
        response = await ai_summary_generator.summarize_items(
            items=request.items,
            context="market data"
        )
        return response
    except Exception as e:
        logger.error(f"Error generating AI summary: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {str(e)}"
        )


@app.get("/ai/briefing-summary", response_model=AISummaryResponse, tags=["AI"])
async def get_briefing_ai_summary(
    focus_symbols: Optional[str] = Query(
        None,
        description="Comma-separated list of symbols to focus on"
    )
):
    """
    Generate an AI-powered summary of the current briefing.
    
    This provides a one-click executive summary highlighting:
    - Key market-moving events
    - Critical trading signals
    - Risk factors to watch
    """
    symbols = watchlist_manager.get_symbols()
    
    if not symbols:
        raise HTTPException(
            status_code=400,
            detail="Watchlist is empty. Add symbols first."
        )
    
    # Parse focus symbols
    focus = None
    if focus_symbols:
        focus = [s.strip().upper() for s in focus_symbols.split(",")]
    
    try:
        # Generate briefing first
        report = await briefing_generator.generate(symbols=symbols)
        
        # Generate AI summary
        response = await ai_summary_generator.summarize_briefing(
            news=report.company_news,
            macro=report.macro_events,
            filings=report.sec_filings,
            stock_summaries=report.stock_summaries,
            focus_symbols=focus
        )
        
        return response
    except Exception as e:
        logger.error(f"Error generating AI briefing summary: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {str(e)}"
        )


# ============== Storylines (MorningEdge Timeline) ==============

class StorylineResponse(BaseModel):
    """Deprecated storyline shape; API returns []. id as str for bigint precision."""
    id: str
    ticker: str
    canonical_theme: str
    summary: str
    title: Optional[str] = None
    story_type: Optional[str] = None  # 'short' | 'filing'
    source_storyline_id: Optional[str] = None  # when story_type='filing', the storyline id that triggered this insight
    citations: Optional[List[str]] = None  # for story_type='filing': chunk IDs e.g. filing_123_chunk_4
    created_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    latest_article_published_at: Optional[datetime] = None  # max published_at of linked articles; used for timeline date


class StorylineArticleResponse(BaseModel):
    """Deprecated; API returns []."""
    id: int
    ticker: str
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[datetime] = None
    relation_type: Optional[str] = None


def _ensure_tz(dt: Any) -> Optional[datetime]:
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


@app.get("/storylines", response_model=List[StorylineResponse], tags=["Storylines"])
async def get_storylines(
    ticker: str = Query(..., description="Stock ticker symbol"),
    days: Optional[int] = Query(None, ge=1, le=90, description="Only return storylines with last_updated_at in the last N days (UTC). Ignored if start_date or end_date is provided."),
    start_date: Optional[datetime] = Query(None, description="Start date (inclusive) in ISO format. Filters by latest_article_published_at (fallback: last_updated_at, created_at)."),
    end_date: Optional[datetime] = Query(None, description="End date (inclusive) in ISO format. Filters by latest_article_published_at (fallback: last_updated_at, created_at)."),
):
    """
    List storylines for a ticker (for MorningEdge Timeline, category Stock).
    Deprecated: returns empty list. Use /stories and long-stories APIs instead.
    """
    return []


# ============== Overnight Stories (overnight pipeline: story table) ==============

class OvernightStoryResponse(BaseModel):
    """One overnight story for a ticker (story table). id as str for bigint-safe frontend."""
    id: str
    ticker: Optional[str] = None
    asof_date: str  # YYYY-MM-DD
    title: str
    summary: str
    topics: List[str] = []
    session_label: str  # OVERNIGHT, INTRADAY, MIXED, UNKNOWN
    session_confidence: Optional[float] = None
    prob_move_ge_1pct: Optional[float] = None
    prob_move_ge_2pct: Optional[float] = None
    expected_abs_move_pct: Optional[float] = None
    direction_bias: Optional[str] = None  # UP, DOWN, NEUTRAL, MIXED
    risk_confidence: Optional[float] = None
    risk_drivers: List[str] = []
    is_filing_related: bool = False
    created_at: Optional[datetime] = None
    latest_article_published_at: Optional[datetime] = None


def _parse_datetime_param(s: Optional[str]) -> Optional[datetime]:
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


def _parse_latest_from_event_time_evidence(evidence: Any) -> Optional[datetime]:
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
        # Extract datetime part: "published_at=2026-02-05T18:30:00Z" -> "2026-02-05T18:30:00Z"
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


@app.get("/overnight-stories", response_model=List[OvernightStoryResponse], tags=["Overnight Stories"])
async def get_overnight_stories(
    ticker: str = Query(..., description="Stock ticker symbol"),
    start_date: Optional[str] = Query(None, description="Start date ISO8601 (inclusive) for latest_article_published_at filtering"),
    end_date: Optional[str] = Query(None, description="End date ISO8601 (inclusive) for latest_article_published_at filtering"),
):
    """
    List overnight pipeline stories for a ticker.
    Filters by event_time_evidence: takes the latest parseable datetime from event_time_evidence;
    stories with empty event_time_evidence are excluded. Date range uses [start_date, end_date].
    Returns id as string (bigint-safe). latest_article_published_at = latest time from event_time_evidence.
    """
    from backend.storage.supabase_client import get_supabase_client
    try:
        supabase = get_supabase_client()
        t = ticker.strip().upper()
        # Fetch by ticker + session_label only; date filtering done in Python using event_time_evidence
        query = (
            supabase.table("story")
            .select("id, asof_date, ticker, title, summary, topics, session_label, session_confidence, "
                    "event_time_evidence, prob_move_ge_1pct, prob_move_ge_2pct, expected_abs_move_pct, direction_bias, "
                    "risk_confidence, risk_drivers, is_filing_related, created_at")
            .eq("ticker", t)
            .in_("session_label", ["OVERNIGHT", "INTRADAY", "MIXED"])
            .order("created_at", desc=True)
        )
        result = query.execute()
        rows = result.data or []
        start_dt = _parse_datetime_param(start_date)
        end_dt = _parse_datetime_param(end_date)
        if not rows:
            return []

        out: List[OvernightStoryResponse] = []
        for r in rows:
            evidence = r.get("event_time_evidence")
            event_time = _parse_latest_from_event_time_evidence(evidence)
            sid = r["id"]
            skip_reason = None
            if event_time is None:
                skip_reason = "event_time_none"
            elif start_dt is not None and event_time < start_dt:
                skip_reason = "before_start"
            elif end_dt is not None and event_time > end_dt:
                skip_reason = "after_end"
            if skip_reason:
                continue

            asof = r.get("asof_date")
            if asof and hasattr(asof, "isoformat"):
                asof_str = asof.isoformat()[:10]
            else:
                asof_str = str(asof)[:10] if asof else ""
            risk_drivers = r.get("risk_drivers")
            if risk_drivers is not None and not isinstance(risk_drivers, list):
                risk_drivers = []

            # Use event_time as latest_article_published_at for display/sorting
            out.append(OvernightStoryResponse(
                id=str(sid),
                ticker=r.get("ticker"),
                asof_date=asof_str,
                title=(r.get("title") or "").strip() or "",
                summary=(r.get("summary") or "").strip() or "",
                topics=r.get("topics") or [],
                session_label=(r.get("session_label") or "UNKNOWN").strip(),
                session_confidence=r.get("session_confidence"),
                prob_move_ge_1pct=r.get("prob_move_ge_1pct"),
                prob_move_ge_2pct=r.get("prob_move_ge_2pct"),
                expected_abs_move_pct=r.get("expected_abs_move_pct"),
                direction_bias=r.get("direction_bias"),
                risk_confidence=r.get("risk_confidence"),
                risk_drivers=risk_drivers or [],
                is_filing_related=bool(r.get("is_filing_related")),
                created_at=r.get("created_at"),
                latest_article_published_at=event_time,
            ))
        # Sort by event time descending
        _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        out.sort(key=lambda x: (x.latest_article_published_at or _epoch), reverse=True)
        return out
    except Exception as e:
        logger.error("Error fetching overnight stories for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/overnight-stories/{story_id}/articles", response_model=List[StorylineArticleResponse], tags=["Overnight Stories"])
async def get_overnight_story_articles(story_id: str):
    """List articles linked to an overnight story (story_article_link + news_articles)."""
    from backend.storage.supabase_client import get_supabase_client
    try:
        story_id_int = int(story_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid story_id")
    try:
        supabase = get_supabase_client()
        link_result = (
            supabase.table("story_article_link")
            .select("article_id, role")
            .eq("story_id", story_id_int)
            .execute()
        )
        links = link_result.data or []
        if not links:
            return []
        article_ids = [l["article_id"] for l in links]
        link_map = {l["article_id"]: l.get("role") for l in links}
        art_result = (
            supabase.table("news_articles")
            .select("id, ticker, title, summary, url, source, published_at")
            .in_("id", article_ids)
            .execute()
        )
        articles = art_result.data or []
        out = []
        for a in articles:
            aid = a.get("id")
            out.append(
                StorylineArticleResponse(
                    id=aid,
                    ticker=a.get("ticker") or "",
                    title=a.get("title") or "",
                    summary=a.get("summary"),
                    url=a.get("url"),
                    source=a.get("source"),
                    published_at=a.get("published_at"),
                    relation_type=link_map.get(aid),
                )
            )
        out.sort(key=lambda x: (x.published_at or datetime.min), reverse=True)
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching overnight story articles for %s: %s", story_id, e)
        raise HTTPException(status_code=500, detail=str(e))


def _filing_display_title(form_type: Optional[str], filed_date: Optional[str], fiscal_year: Optional[int], period: Optional[str]) -> str:
    """Human-readable filing name, e.g. '10-Q · Q3 2024' or '10-K · FY 2024'."""
    form = (form_type or "").strip() or "Filing"
    if fiscal_year is not None and period:
        return f"{form} · {period} {fiscal_year}"
    if filed_date:
        year = str(filed_date)[:4] if len(str(filed_date)) >= 4 else ""
        return f"{form} · {year}" if year else form
    return form


def _looks_like_table(text: str) -> bool:
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


class FilingCitationItem(BaseModel):
    """One filing citation: human-readable title, optional LLM summary sentence, chunk text, filing URL; is_table hints frontend to render as table."""
    chunk_id: str
    filing_title: str
    summary: Optional[str] = None  # LLM-generated one-sentence rephrase/summary of this excerpt
    text: str
    filing_url: str
    form_type: Optional[str] = None
    filed_date: Optional[str] = None
    is_table: bool = False


@app.get("/overnight-stories/{story_id}/filing-chunks", response_model=List[FilingCitationItem], tags=["Overnight Stories"])
async def get_overnight_story_filing_chunks(story_id: str):
    """Return SEC filing chunk(s) linked to an overnight story (story_filing_link + top_chunk_id -> sec_filing_chunks)."""
    from backend.storage.supabase_client import get_supabase_client
    try:
        story_id_int = int(story_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid story_id")
    try:
        supabase = get_supabase_client()
        link_result = (
            supabase.table("story_filing_link")
            .select("filing_id, top_chunk_id")
            .eq("story_id", story_id_int)
            .limit(1)
            .execute()
        )
        if not link_result.data or len(link_result.data) == 0:
            return []
        row = link_result.data[0]
        filing_id = row.get("filing_id")
        top_chunk_id = row.get("top_chunk_id")
        if filing_id is None:
            return []
        filing_row = (
            supabase.table("sec_filings")
            .select("url, form_type, filed_date, fiscal_year, period")
            .eq("id", filing_id)
            .limit(1)
            .execute()
        )
        filing_url = ""
        form_type = None
        filed_date = None
        fiscal_year = None
        period = None
        if filing_row.data and len(filing_row.data) > 0:
            f = filing_row.data[0]
            filing_url = f.get("url") or ""
            form_type = f.get("form_type")
            fd = f.get("filed_date")
            filed_date = str(fd)[:10] if fd else None
            try:
                fiscal_year = int(f["fiscal_year"]) if f.get("fiscal_year") is not None else None
            except (TypeError, ValueError):
                fiscal_year = None
            period = (f.get("period") or "").strip() or None
        filing_title = _filing_display_title(form_type, filed_date, fiscal_year, period)
        if top_chunk_id is None:
            return []
        chunk_row = (
            supabase.table("sec_filing_chunks")
            .select("id, text")
            .eq("id", top_chunk_id)
            .limit(1)
            .execute()
        )
        if not chunk_row.data or len(chunk_row.data) == 0:
            return []
        chunk_data = chunk_row.data[0]
        chunk_text = chunk_data.get("text") or ""
        is_table = _looks_like_table(chunk_text)
        return [FilingCitationItem(
            chunk_id=str(top_chunk_id),
            filing_title=filing_title,
            summary=None,
            text=chunk_text,
            filing_url=filing_url,
            form_type=form_type,
            filed_date=filed_date,
            is_table=is_table,
        )]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching overnight story filing chunks for %s: %s", story_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/storylines/{storyline_id}/filing-citations", response_model=List[FilingCitationItem], tags=["Storylines"])
async def get_storyline_filing_citations(storyline_id: str):
    """Deprecated; returns []."""
    return []


class FormatFilingChunkRequest(BaseModel):
    """Request body for formatting a raw SEC filing chunk into human-readable form."""
    chunk_text: str


class FormatFilingChunkResponse(BaseModel):
    """Human-readable formatted chunk: markdown table or clear paragraphs."""
    formatted: str


@app.post("/storylines/format-filing-chunk", response_model=FormatFilingChunkResponse, tags=["Storylines"])
async def format_filing_chunk(request: FormatFilingChunkRequest):
    """
    Convert raw SEC filing chunk text to human-readable format using LLM.
    If the content is tabular (numbers, columns), output a markdown table.
    If prose, output clear full sentences/paragraphs.
    """
    from openai import AsyncOpenAI
    from backend.config import OPENAI_API_KEY, OPENAI_MODEL
    raw = (request.chunk_text or "").strip()
    if not raw or len(raw) > 15000:
        raise HTTPException(status_code=400, detail="chunk_text required and must be under 15000 characters")
    system_content = (
        "You are a financial document formatter. You will receive a raw excerpt from an SEC filing (10-K, 10-Q, etc.). "
        "Your task is to convert it to human-readable format ONLY. Do not add commentary or interpretation. "
        "Rules: "
        "1. If the content is clearly tabular (columns of numbers, regions, dates, percentages), output a markdown table with pipe separators (e.g. | Region | Q3 2025 | Q3 2024 | Change |). Use a header row and a separator row (|---|---|---|). "
        "2. If the content is prose (paragraphs, sentences), output clear full sentences with proper line breaks between paragraphs. "
        "3. Preserve all numbers, dates, and facts exactly. Output only the formatted content, no preamble."
    )
    user_content = f"""Format this SEC filing excerpt into human-readable form (markdown table if tabular, clear paragraphs if prose):

{raw[:12000]}"""

    try:
        if not OPENAI_API_KEY:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        model = OPENAI_MODEL
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        formatted = (response.choices[0].message.content or "").strip()
        if not formatted:
            formatted = raw
        return FormatFilingChunkResponse(formatted=formatted)
    except Exception as e:
        logger.error(f"Format filing chunk LLM failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to format chunk")


@app.get("/storylines/{storyline_id}/articles", response_model=List[StorylineArticleResponse], tags=["Storylines"])
async def get_storyline_articles(storyline_id: str):
    """Deprecated; returns []."""
    return []


class StorylineTimelineMonth(BaseModel):
    """Articles for one month in a long-story timeline."""
    month: str  # e.g. "2024-01"
    articles: List[StorylineArticleResponse]


class StorylineTimelineResponse(BaseModel):
    """Time-bucketed (by month) articles for long-story view: how the news evolves. Includes title, summary, theme for UI."""
    title: Optional[str] = None
    summary: Optional[str] = None
    theme: Optional[str] = None  # canonical_theme
    total_articles: int = 0
    months: List[StorylineTimelineMonth]


@app.get("/storylines/{storyline_id}/timeline", response_model=StorylineTimelineResponse, tags=["Storylines"])
async def get_storyline_timeline(storyline_id: str):
    """Deprecated; returns empty timeline."""
    return StorylineTimelineResponse(title=None, summary=None, theme=None, total_articles=0, months=[])


# ============== Long Stories ==============

class LongStoryResponse(BaseModel):
    """One long story for a ticker (long_stories row). id as str for bigint."""
    id: str
    ticker: str
    title: Optional[str] = None
    canonical_theme: Optional[str] = None
    summary: Optional[str] = None
    impact_level: Optional[str] = None
    article_count: Optional[int] = None
    created_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    latest_article_published_at: Optional[datetime] = None  # max published_at of linked articles; used for timeline date


@app.get("/long-stories", response_model=List[LongStoryResponse], tags=["Long Stories"])
async def get_long_stories(
    ticker: str = Query(..., description="Stock ticker symbol"),
):
    """
    List all long stories for a ticker (no date filter).
    Returns long stories ordered by last_updated_at desc.
    Used by the Long Story tab in stock detail; timeline date range does not affect this list.
    """
    from backend.storage.supabase_client import get_supabase_client
    try:
        supabase = get_supabase_client()
        query = (
            supabase.table("long_stories")
            .select("id, ticker, title, canonical_theme, summary, created_at, last_updated_at")
            .eq("ticker", ticker.strip().upper())
            .order("last_updated_at", desc=True)
        )
        result = query.execute()
        rows = result.data if result.data else []
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        count_by_id = {}
        latest_article_by_story: Dict[int, Any] = {}
        try:
            link_result = (
                supabase.table("long_story_article_links")
                .select("long_story_id, article_id")
                .in_("long_story_id", ids)
                .execute()
            )
            from collections import Counter
            link_data = link_result.data or []
            count_by_id = dict(Counter(row["long_story_id"] for row in link_data))
            if link_data:
                article_ids = list({row["article_id"] for row in link_data})
                art_result = (
                    supabase.table("news_articles")
                    .select("id, published_at")
                    .in_("id", article_ids)
                    .execute()
                )
                articles = art_result.data or []
                pub_by_article = {a["id"]: a.get("published_at") for a in articles if a.get("published_at")}
                for link in link_data:
                    lsid, aid = link.get("long_story_id"), link.get("article_id")
                    if lsid is not None and aid is not None:
                        pub = pub_by_article.get(aid)
                        if pub:
                            cur = latest_article_by_story.get(lsid)
                            if cur is None or str(pub) > str(cur):
                                latest_article_by_story[lsid] = pub
        except Exception as e:
            logger.warning("Could not fetch long_story article counts or latest dates: %s", e)
        return [
            LongStoryResponse(
                id=str(r["id"]),
                ticker=r["ticker"],
                title=r.get("title"),
                canonical_theme=r.get("canonical_theme"),
                summary=r.get("summary"),
                impact_level=r.get("impact_level"),
                article_count=count_by_id.get(r["id"], 0),
                created_at=r.get("created_at"),
                last_updated_at=r.get("last_updated_at"),
                latest_article_published_at=latest_article_by_story.get(r["id"]),
            )
            for r in rows
        ]
    except Exception as e:
        if "does not exist" in str(e).lower():
            return []
        logger.error("Error fetching long stories for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/long-stories/{long_story_id}/timeline", response_model=StorylineTimelineResponse, tags=["Long Stories"])
async def get_long_story_timeline(long_story_id: str):
    """
    Returns articles linked to a long story grouped by month (same shape as storyline timeline).
    """
    from backend.storage.supabase_client import get_supabase_client
    from collections import defaultdict
    try:
        story_id_int = int(long_story_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid long_story_id")
    try:
        supabase = get_supabase_client()
        story_row = (
            supabase.table("long_stories")
            .select("title, summary, canonical_theme")
            .eq("id", story_id_int)
            .limit(1)
            .execute()
        )
        title = None
        summary = None
        theme = None
        if story_row.data and len(story_row.data) > 0:
            row = story_row.data[0]
            title = row.get("title") or row.get("canonical_theme")
            summary = row.get("summary")
            theme = row.get("canonical_theme")
        link_result = (
            supabase.table("long_story_article_links")
            .select("article_id, relation_type")
            .eq("long_story_id", story_id_int)
            .execute()
        )
        links = link_result.data if link_result.data else []
        if not links:
            return StorylineTimelineResponse(title=title, summary=summary, theme=theme, total_articles=0, months=[])
        article_ids = [l["article_id"] for l in links]
        link_map = {l["article_id"]: l.get("relation_type") for l in links}
        art_result = (
            supabase.table("news_articles")
            .select("id, ticker, title, summary, url, source, published_at")
            .in_("id", article_ids)
            .execute()
        )
        articles = art_result.data if art_result.data else []
        by_month: dict = defaultdict(list)
        for a in articles:
            pub = a.get("published_at")
            month_key = pub[:7] if isinstance(pub, str) and len(pub) >= 7 else "unknown"
            by_month[month_key].append(
                StorylineArticleResponse(
                    id=a.get("id"),
                    ticker=a.get("ticker") or "",
                    title=a.get("title") or "",
                    summary=a.get("summary"),
                    url=a.get("url"),
                    source=a.get("source"),
                    published_at=a.get("published_at"),
                    relation_type=link_map.get(a.get("id")),
                )
            )
        for month_key in by_month:
            by_month[month_key].sort(key=lambda x: (x.published_at or datetime.min), reverse=True)
        months_sorted = sorted(by_month.keys(), reverse=True)
        total_articles = len(articles)
        return StorylineTimelineResponse(
            title=title,
            summary=summary,
            theme=theme,
            total_articles=total_articles,
            months=[StorylineTimelineMonth(month=m, articles=by_month[m]) for m in months_sorted],
        )
    except Exception as e:
        if "does not exist" in str(e).lower():
            raise HTTPException(status_code=404, detail="Long story or table not found")
        logger.error("Error fetching long story timeline for %s: %s", long_story_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ============== Discover Feed ==============

class DiscoverFeedItem(BaseModel):
    """One card for Discover tab: high-impact short storylines + recently updated long stories."""
    ticker: str
    name: str
    price: float = 0.0
    change_percent: float = 0.0
    headline: str
    impact_rating: Optional[str] = None  # 'high' | 'medium' | 'low'
    story_type: str  # 'short' | 'long'
    storyline_id: Optional[str] = None  # for short
    long_story_id: Optional[str] = None  # for long
    last_updated_at: Optional[datetime] = None
    chart_data: Optional[List[float]] = None  # optional last 9 closes for mini chart


def _impact_score_to_level(score: Optional[float]) -> str:
    """Derive display level from impact_score (0–1). Null -> medium."""
    if score is None:
        return "medium"
    if score >= 0.7:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


def _sort_key_impact_score(item: Dict[str, Any]) -> Tuple[bool, float]:
    """Sort key: (nulls last, -score) so higher score first, nulls last."""
    s = item.get("impact_score")
    if s is None:
        return (True, 0.0)  # nulls after
    try:
        return (False, -float(s))
    except (TypeError, ValueError):
        return (True, 0.0)


@app.get("/discover/feed", response_model=List[DiscoverFeedItem], tags=["Discover"])
async def get_discover_feed(
    short_limit: int = Query(20, ge=1, le=50, description="Max short storylines to consider"),
    long_days: int = Query(7, ge=1, le=30, description="Long stories updated in last N days"),
    top: int = Query(10, ge=1, le=30, description="Max items to return (most impactful first)"),
):
    """
    Feed for Discover tab: most impactful storylines and long stories (sorted by impact then recency).
    Returns up to `top` items. Price/change can be 0; frontend may overlay from /stocks/prices.
    """
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.stocks_query import get_stocks
    try:
        supabase = get_supabase_client()
        cutoff = (datetime.utcnow() - timedelta(days=long_days)).isoformat()
        items: List[Dict[str, Any]] = []

        # Long stories: updated in last long_days days
        try:
            long_result = (
                supabase.table("long_stories")
                .select("id, ticker, title, canonical_theme, summary, impact_level, impact_score, last_updated_at")
                .gte("last_updated_at", cutoff)
                .order("last_updated_at", desc=True)
                .limit(short_limit)
                .execute()
            )
            long_rows = long_result.data or []
            for r in long_rows:
                score = r.get("impact_score")
                if score is not None:
                    try:
                        score = float(score)
                    except (TypeError, ValueError):
                        score = None
                impact_rating = _impact_score_to_level(score) if score is not None else ((r.get("impact_level") or "").strip().lower() or "medium")
                if impact_rating not in ("high", "medium", "low"):
                    impact_rating = "medium"
                headline = (r.get("title") or r.get("canonical_theme") or r.get("summary") or "").strip() or "Long story"
                items.append({
                    "ticker": (r.get("ticker") or "").strip().upper(),
                    "headline": headline[:200],
                    "impact_rating": impact_rating,
                    "impact_score": score,
                    "story_type": "long",
                    "storyline_id": None,
                    "long_story_id": str(r["id"]),
                    "last_updated_at": r.get("last_updated_at"),
                })
        except Exception as e:
            if "does not exist" not in str(e).lower():
                logger.warning("Discover long stories: %s", e)

        if not items:
            return []

        # Sort by impact_score descending (nulls last), then by last_updated_at desc
        items.sort(key=lambda x: (x.get("last_updated_at") or ""), reverse=True)
        items.sort(key=_sort_key_impact_score)
        items = items[:top]
        tickers = list({x["ticker"] for x in items if x["ticker"]})
        name_by_ticker: Dict[str, str] = {}
        try:
            stocks = get_stocks(supabase, tickers)
            for s in stocks or []:
                t = (s.get("ticker") or "").strip().upper()
                if t:
                    name_by_ticker[t] = (s.get("name") or s.get("ticker") or t)
        except Exception as e:
            logger.debug("Discover get_stocks: %s", e)
        out = []
        for x in items:
            t = x["ticker"]
            out.append(DiscoverFeedItem(
                ticker=t,
                name=name_by_ticker.get(t, t),
                price=0.0,
                change_percent=0.0,
                headline=x["headline"],
                impact_rating=x.get("impact_rating"),
                story_type=x["story_type"],
                storyline_id=x.get("storyline_id"),
                long_story_id=x.get("long_story_id"),
                last_updated_at=x.get("last_updated_at"),
                chart_data=None,
            ))
        return out
    except Exception as e:
        logger.error("Error fetching discover feed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class AskHistoryEntry(BaseModel):
    """One turn in Ask conversation for follow-up context."""
    role: str  # "user" | "assistant"
    content: str


class CustomStoryRequest(BaseModel):
    """User-created story: question only (not persisted). Supports single ticker or multiple tickers for relationship questions. Optional history for follow-up context (last 3 rounds)."""
    ticker: Optional[str] = None  # backward compat: used when tickers not provided
    tickers: Optional[List[str]] = None  # multiple tickers, e.g. for "relationship between AAPL and MSFT"
    question: str
    history: Optional[List[AskHistoryEntry]] = None  # previous Q&A for follow-up; backend caps to 3 rounds (6 messages)


class CustomStoryArticle(BaseModel):
    """Article returned for custom story (same shape as StorylineArticleResponse)."""
    id: int
    ticker: str
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[datetime] = None


class MacroSourceItem(BaseModel):
    """One macro brief used as RAG context."""
    topic: str
    title: Optional[str] = None
    as_of_date: Optional[str] = None


class CustomStoryResponse(BaseModel):
    """Response for POST /storylines/custom — answer + articles or macro_sources; no DB persistence."""
    answer: str
    articles: List[CustomStoryArticle] = []
    context_type: str = "stock"  # "stock" | "macro"
    macro_sources: Optional[List[MacroSourceItem]] = None
    detected_tickers: Optional[List[str]] = None


# Ask (custom story) concurrency cap; lazy-initialized from ASK_MAX_CONCURRENT
_ask_semaphore: Optional[asyncio.Semaphore] = None

def _get_ask_semaphore() -> Optional[asyncio.Semaphore]:
    global _ask_semaphore
    if _ask_semaphore is None:
        from backend.config import ASK_MAX_CONCURRENT
        _ask_semaphore = asyncio.Semaphore(ASK_MAX_CONCURRENT) if ASK_MAX_CONCURRENT > 0 else None
    return _ask_semaphore


@app.post("/storylines/custom", response_model=CustomStoryResponse, tags=["Storylines"])
async def create_custom_story(request: CustomStoryRequest, http_request: Request):
    """
    User-created story: answer a question using relevant articles (embed → retrieve → rerank → generate).
    Not persisted; UI chatbot only. Query length gated by CUSTOM_STORY_QUERY_MAX_CHARS.
    Rate limited and optional daily quota per IP; configurable token/context caps.
    """
    from backend.config import (
        CUSTOM_STORY_QUERY_MAX_CHARS, RAG_TOP_K_CANDIDATES,
        CUSTOM_STORY_MAX_TOKENS, CUSTOM_STORY_CONTEXT_ARTICLES, CUSTOM_STORY_ARTICLE_SUMMARY_CHARS,
    )
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.embedding_utils import get_embeddings
    from backend.pipeline.rag_retrieval import retrieve_similar_news
    from backend.pipeline.rerank import rerank
    from backend.services.ask_limits import check_ask_limits, record_ask
    from openai import AsyncOpenAI
    from backend.config import OPENAI_API_KEY, OPENAI_MODEL

    client_ip = http_request.client.host if http_request.client else "unknown"
    limited = await check_ask_limits(client_ip)
    if limited:
        retry_after, detail = limited
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )

    sem = _get_ask_semaphore()
    if sem:
        await sem.acquire()
    try:
        return await _create_custom_story_impl(request, client_ip)
    finally:
        if sem:
            sem.release()


async def _create_custom_story_impl(request: CustomStoryRequest, client_ip: str) -> CustomStoryResponse:
    """Implementation of create_custom_story (after rate/quota check and semaphore acquire)."""
    from backend.config import (
        CUSTOM_STORY_QUERY_MAX_CHARS, RAG_TOP_K_CANDIDATES,
        CUSTOM_STORY_MAX_TOKENS, CUSTOM_STORY_CONTEXT_ARTICLES, CUSTOM_STORY_ARTICLE_SUMMARY_CHARS,
    )
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.embedding_utils import get_embeddings
    from backend.storage.stocks_query import get_stock, get_all_stocks
    from backend.storage.macro_brief_by_asset_query import get_all_briefs_for_date
    from backend.pipeline.rag_retrieval import retrieve_similar_news
    from backend.pipeline.rerank import rerank
    from backend.services.ask_limits import record_ask
    from backend.services.ask_extract import extract_tickers_or_macro
    from openai import AsyncOpenAI
    from backend.config import OPENAI_API_KEY, OPENAI_MODEL

    question = (request.question or "").strip()
    raw_tickers = request.tickers if (request.tickers and len(request.tickers) > 0) else ([request.ticker] if request.ticker else [])
    tickers_list = []
    seen = set()
    for t in raw_tickers:
        u = (t or "").strip().upper()
        if u and u not in seen:
            seen.add(u)
            tickers_list.append(u)

    # If no tickers provided: extract from question (tickers or macro)
    if not tickers_list:
        if len(question) > CUSTOM_STORY_QUERY_MAX_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"Question exceeds max length ({CUSTOM_STORY_QUERY_MAX_CHARS} chars). Shorten your question.",
            )
        if not question:
            raise HTTPException(status_code=400, detail="question is required")
        supabase = get_supabase_client()
        stocks = get_all_stocks(supabase)
        ticker_name_pairs = [(s.get("ticker") or "", s.get("name") or s.get("ticker") or "") for s in stocks if s.get("ticker")]
        if not OPENAI_API_KEY:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        model = OPENAI_MODEL
        tickers_list, is_macro = await extract_tickers_or_macro(question, ticker_name_pairs, client, model)

        if is_macro:
            # Macro path: fetch recent macro briefs, build context, LLM answer
            today = date.today()
            macro_context_parts = []
            macro_sources_list = []
            max_brief_chars = 800
            total_context_chars = 0
            max_total = 6000
            for d in range(7):
                as_of = today - timedelta(days=d)
                briefs = get_all_briefs_for_date(supabase, as_of, topic=None, full=False)
                for b in briefs:
                    topic = b.get("topic") or ""
                    title = b.get("title") or ""
                    summary = (b.get("summary") or "")[:max_brief_chars]
                    block = f"[{as_of.isoformat()}] {topic}: {title}\n{summary}\n"
                    if total_context_chars + len(block) > max_total:
                        continue
                    macro_context_parts.append(block)
                    total_context_chars += len(block)
                    macro_sources_list.append(MacroSourceItem(topic=topic, title=title or None, as_of_date=as_of.isoformat()))
            macro_context = "\n".join(macro_context_parts) if macro_context_parts else "No macro briefs available for the past week."
            current_prompt = f"""The user asked: "{question}"

Relevant macro briefs (for context):
{macro_context}

Write a concise answer (2–4 paragraphs) using these macro briefs. If there is little relevant content, say so briefly."""
            # Build messages with optional previous context (up to 3 rounds = 6 messages)
            _history = (request.history or [])[:6]
            history_entries = [h for h in _history if h.role in ("user", "assistant") and (h.content or "").strip()]
            messages = [{"role": "system", "content": "You are a macro analyst. Answer using the provided macro briefs. Be concise and factual. Use previous conversation context when the user asks a follow-up."}]
            for h in history_entries:
                messages.append({"role": h.role, "content": (h.content or "").strip()[:2000]})
            messages.append({"role": "user", "content": current_prompt})

            max_tokens = max(100, min(CUSTOM_STORY_MAX_TOKENS, 2000))
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.5,
                    max_tokens=max_tokens,
                )
                answer = (response.choices[0].message.content or "").strip()
            except Exception as e:
                logger.error(f"Ask macro LLM failed: {e}")
                answer = "Unable to generate an answer from macro briefs at this time."
            await record_ask(client_ip)
            return CustomStoryResponse(
                answer=answer,
                articles=[],
                context_type="macro",
                macro_sources=macro_sources_list[:20],
                detected_tickers=[],
            )

        if not tickers_list:
            await record_ask(client_ip)
            return CustomStoryResponse(
                answer="I couldn't identify specific tickers or a macro focus from your question. Try mentioning company names (e.g. Apple, Tesla) or macro topics (e.g. Fed, rates, inflation).",
                articles=[],
                context_type="stock",
                detected_tickers=[],
            )

    if len(question) > CUSTOM_STORY_QUERY_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Question exceeds max length ({CUSTOM_STORY_QUERY_MAX_CHARS} chars). Shorten your question.",
        )
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    supabase = get_supabase_client()
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
    _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    _model = OPENAI_MODEL
    context_parts = []
    for t in tickers_list:
        stock = get_stock(supabase, t)
        name = (stock.get("name") or t) if stock else t
        context_parts.append(f"{t} ({name})")
    context_str = ", ".join(context_parts)
    query_for_embed = f"Context: {context_str}. Question: {question}"
    try:
        embeddings = await get_embeddings([query_for_embed])
        if embeddings is None or embeddings.size == 0:
            raise HTTPException(status_code=503, detail="Embedding service unavailable")
        query_embedding = embeddings[0].tolist()
    except Exception as e:
        logger.error(f"Custom story embedding failed: {e}")
        raise HTTPException(status_code=503, detail="Failed to embed question")
    # RAG: only use articles from the last 6 months to avoid stale context
    rag_start_date = datetime.now(timezone.utc) - timedelta(days=183)
    similar = await retrieve_similar_news(
        supabase,
        tickers_list,
        query_embedding,
        exclude_article_ids=None,
        limit=min(RAG_TOP_K_CANDIDATES, 30),
        start_date=rag_start_date,
    )
    top_n = 10
    reranked = rerank(question, similar, top_n) if similar else []
    articles_for_llm = reranked
    primary_ticker = tickers_list[0]
    article_list = [
        CustomStoryArticle(
            id=a.get("id"),
            ticker=a.get("ticker") or primary_ticker,
            title=a.get("title") or "",
            summary=a.get("summary"),
            url=a.get("url"),
            source=a.get("source"),
            published_at=a.get("published_at"),
        )
        for a in articles_for_llm
    ]
    n_ctx = max(1, min(CUSTOM_STORY_CONTEXT_ARTICLES, 20))
    summary_chars = max(50, min(CUSTOM_STORY_ARTICLE_SUMMARY_CHARS, 1000))
    context = ""
    for i, a in enumerate(articles_for_llm[:n_ctx], 1):
        summary_slice = (a.get("summary") or "")[:summary_chars]
        context += f"{i}. {a.get('title', '')}\n   {summary_slice}\n\n"
    relationship_instruction = ""
    if len(tickers_list) > 1:
        relationship_instruction = " Focus on the relationship or comparison between the given companies where relevant."
    current_prompt = f"""The user asked: "{question}"

Relevant news articles (for context):
{context}

Write a concise, historically-grounded answer (2–4 paragraphs) that uses these articles to address the question.{relationship_instruction} Do not list articles; weave the narrative. If there is little relevant content, say so briefly."""
    # Build messages with optional previous context (up to 3 rounds = 6 messages)
    _history = (request.history or [])[:6]
    history_entries = [h for h in _history if h.role in ("user", "assistant") and (h.content or "").strip()]
    messages = [{"role": "system", "content": "You are a financial news analyst. Answer the user's question using the provided articles. Be concise and factual. Use previous conversation context when the user asks a follow-up."}]
    for h in history_entries:
        messages.append({"role": h.role, "content": (h.content or "").strip()[:2000]})
    messages.append({"role": "user", "content": current_prompt})

    max_tokens = max(100, min(CUSTOM_STORY_MAX_TOKENS, 2000))
    try:
        response = await _client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=0.5,
            max_tokens=max_tokens,
        )
        answer = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"Custom story LLM failed: {e}")
        answer = "Unable to generate an answer at this time. Here are the most relevant articles."
    await record_ask(client_ip)
    return CustomStoryResponse(
        answer=answer,
        articles=article_list,
        context_type="stock",
        detected_tickers=tickers_list,
    )


# ============== Causal Graph ==============

class CausalGraphEdge(BaseModel):
    """Directed edge: from (influencer) -> to (influencee), with optional story context."""
    from_ticker: str
    to_ticker: str
    storyline_id: Optional[str] = None
    article_titles: Optional[List[str]] = None


class CausalGraphResponse(BaseModel):
    """Causal graph: nodes (tickers) and edges (article_ticker -> storyline_ticker)."""
    nodes: List[str]
    edges: List[CausalGraphEdge]


def _expand_causal_graph(all_edges: List[tuple], target: str, levels: int) -> tuple:
    """BFS from target for `levels` steps. Return (set of nodes, list of (from, to) edges)."""
    target = (target or "").strip().upper()
    if not target:
        return set(), []
    edges = []
    for a, b in all_edges:
        if a and b:
            a, b = a.strip().upper(), b.strip().upper()
            if a and b and a != b:
                edges.append((a, b))
    if not edges:
        return {target}, []

    frontier = {target}
    included_nodes = {target}
    included_edges = set()

    for _ in range(levels):
        next_frontier = set()
        for (a, b) in edges:
            if a in frontier or b in frontier:
                included_edges.add((a, b))
                included_nodes.add(a)
                included_nodes.add(b)
                next_frontier.add(a)
                next_frontier.add(b)
        frontier = next_frontier

    return included_nodes, list(included_edges)


@app.get("/causal-graph", response_model=CausalGraphResponse, tags=["Storylines"])
async def get_causal_graph(
    ticker: str = Query(..., description="Target stock ticker symbol"),
    levels: int = Query(3, ge=1, le=5, description="Expansion depth (1-5)")
):
    """Deprecated; returns empty graph."""
    return CausalGraphResponse(nodes=[], edges=[])


# ============== Stock News ==============

class StockNewsItem(BaseModel):
    """Stock news item response model."""
    id: int
    ticker: str
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: str
    published_at: datetime


@app.get("/news/stock", response_model=List[StockNewsItem], tags=["News"])
async def get_stock_news(
    ticker: str = Query(..., description="Stock ticker symbol"),
    start_date: Optional[datetime] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[datetime] = Query(None, description="End date (inclusive)"),
    limit: int = Query(100, description="Maximum number of results", ge=1, le=1000)
):
    """
    Get stock news articles for a specific ticker.
    
    Returns news articles from the news_articles table, filtered by:
    - Ticker symbol (required)
    - Date range (start_date and end_date, optional)
    """
    from backend.storage.news_articles_query import get_articles
    from backend.storage.supabase_client import get_supabase_client
    
    try:
        supabase = get_supabase_client()
        
        articles = get_articles(
            supabase=supabase,
            ticker=ticker.upper().strip(),
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        # Convert to response format
        result = []
        for article in articles:
            result.append(StockNewsItem(
                id=article.get("id"),
                ticker=article.get("ticker", ""),
                title=article.get("title", ""),
                summary=article.get("summary"),
                url=article.get("url"),
                source=article.get("source", "Unknown"),
                published_at=article.get("published_at")
            ))
        
        return result
    except Exception as e:
        logger.error(f"Error fetching stock news: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch stock news: {str(e)}"
        )


# ============== Macro News ==============

class MacroNewsItem(BaseModel):
    """Macro news item response model."""
    id: int
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: str
    published_at: datetime
    primary_topic: Optional[str] = None
    related_tickers: Optional[List[str]] = None


@app.get("/news/macro", response_model=List[MacroNewsItem], tags=["News"])
async def get_macro_news(
    ticker: Optional[str] = Query(None, description="Filter by related tickers (if ticker appears in related_tickers)"),
    start_date: Optional[datetime] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[datetime] = Query(None, description="End date (inclusive)"),
    limit: int = Query(100, description="Maximum number of results", ge=1, le=1000)
):
    """
    Get macro economic news articles.
    
    Returns macro news from the macro_articles table, optionally filtered by:
    - Related tickers (if ticker parameter provided, checks related_tickers JSONB array)
    - Date range (start_date and end_date)
    - Collector (defaults to "alpha_vantage")
    """
    from backend.storage.macro_articles_query import get_macro_articles
    from backend.storage.supabase_client import get_supabase_client
    
    try:
        supabase = get_supabase_client()
        
        articles = get_macro_articles(
            supabase=supabase,
            collector="alpha_vantage",
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        # Convert to response format
        result = []
        for article in articles:
            result.append(MacroNewsItem(
                id=article.get("id"),
                title=article.get("title", ""),
                summary=article.get("summary"),
                url=article.get("url"),
                source=article.get("source", "Unknown"),
                published_at=article.get("published_at"),
                primary_topic=article.get("primary_topic"),
                related_tickers=article.get("related_tickers")
            ))
        
        return result
    except Exception as e:
        logger.error(f"Error fetching macro news: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch macro news: {str(e)}"
        )


# ============== Stock Prices ==============

@app.get("/prices/5min", response_model=List[Price5MinItem], tags=["Prices"])
async def get_5min_prices(
    ticker: str = Query(..., description="Stock ticker symbol"),
    start_date: Optional[datetime] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[datetime] = Query(None, description="End date (inclusive)"),
    limit: int = Query(10000, description="Maximum number of results", ge=1, le=50000)
):
    """
    Get 5-minute intraday price data for a ticker.
    Returns OHLCV data from stock_prices_5min table, ordered by timestamp ascending.
    """
    from backend.storage.stock_prices_5min_query import get_prices_by_ticker
    from backend.storage.supabase_client import get_supabase_client
    
    try:
        supabase = get_supabase_client()
        
        prices = get_prices_by_ticker(
            supabase=supabase,
            ticker=ticker.upper().strip(),
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        # Convert to response format and sort by timestamp ascending (chart needs chronological order)
        result = []
        for price in prices:
            result.append(Price5MinItem(
                timestamp=price.get("timestamp"),
                open=float(price.get("open", 0)),
                high=float(price.get("high", 0)),
                low=float(price.get("low", 0)),
                close=float(price.get("close", 0)),
                volume=int(price.get("volume", 0))
            ))
        
        # Sort by timestamp ascending for chart
        result.sort(key=lambda x: x.timestamp)
        
        return result
    except Exception as e:
        logger.error(f"Error fetching 5min prices for {ticker}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch 5min prices: {str(e)}"
        )


# ============== Macro Daily (digest briefs + impact) ==============

@app.get("/macro/daily", tags=["Macro"])
async def get_macro_daily(
    date: str = Query(..., description="Date YYYY-MM-DD"),
    full: bool = Query(False, description="Return full report (asset-specific or mechanism, transmission)"),
    topic: Optional[str] = Query(None, description="Filter by topic (e.g. FX, RATE)"),
):
    """
    Get daily macro topic briefs for a date. Returns 8 topic reports from per-asset brief tables (macro_brief_fx, ..., macro_brief_policy).
    Use full=true for full report (asset-specific columns or mechanism, transmission). Optionally filter by topic.
    """
    from datetime import date as date_type
    from backend.storage.macro_brief_by_asset_query import get_all_briefs_for_date
    from backend.storage.supabase_client import get_supabase_client
    try:
        as_of = datetime.strptime(date.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD")
    supabase = get_supabase_client()
    briefs = get_all_briefs_for_date(supabase, as_of, topic=topic, full=full)
    return {"date": date[:10], "briefs": briefs or []}


@app.get("/macro/daily/{date}/impact", tags=["Macro"])
async def get_macro_daily_impact(
    date: str,
    portfolio_id: Optional[str] = Query(None, description="Portfolio id (default report if omitted)"),
):
    """
    Get macro daily impact report for a date (factor_mapping, factor_impacts, report_markdown, signals).
    Returns 404 if no report exists. Use POST to generate (and cache) impact.
    """
    from datetime import datetime
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


@app.post("/macro/daily/{date}/impact", tags=["Macro"])
async def post_macro_daily_impact(
    date: str,
    request: Request,
):
    """
    Generate (and cache) macro daily impact report for a date. Body optional: { "portfolio": {...}, "portfolio_id": "..." }.
    """
    from datetime import datetime
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
        raise HTTPException(status_code=500, detail=str(e))
    if report_id is None:
        raise HTTPException(status_code=502, detail="Impact report generation returned no id")
    report = get_impact_for_date(supabase, as_of_date=as_of, portfolio_id=portfolio_id)
    return report or {"id": report_id}


# ============== Stocks ==============

class StockInfo(BaseModel):
    """Stock information model."""
    ticker: str
    name: str
    exchange: str


@app.get("/stocks/nasdaq100", response_model=List[StockInfo], tags=["Stocks"])
async def get_nasdaq100_stocks():
    """
    Get NASDAQ 100 stock list with company names and exchange.
    
    Returns a list of NASDAQ 100 stocks that can be added to watchlist.
    """
    from backend.storage.nasdaq100_tickers import get_nasdaq100_stocks
    
    try:
        stocks = get_nasdaq100_stocks(use_api=False)
        return [
            StockInfo(
                ticker=stock["ticker"],
                name=stock["name"],
                exchange=stock.get("exchange", "NASDAQ")
            )
            for stock in stocks
        ]
    except Exception as e:
        logger.error(f"Error fetching NASDAQ 100 stocks: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch NASDAQ 100 stocks: {str(e)}"
        )


class StockPriceInfo(BaseModel):
    """Stock price information from Alpaca market data."""
    symbol: str
    name: Optional[str] = None
    price: float
    change: float
    changePercent: float
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volume: Optional[int] = None
    timestamp: Optional[datetime] = None
    extendedChange: Optional[float] = None
    extendedChangePercent: Optional[float] = None


class CandlestickBar(BaseModel):
    """Single candlestick bar for charting."""
    time: str  # Unix timestamp as string for lightweight-charts
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None


class HistoricalBarsResponse(BaseModel):
    """Historical bars for TradingView charts."""
    symbol: str
    bars: List[CandlestickBar]
    timeframe: str


@app.get("/stocks/prices", response_model=List[StockPriceInfo], tags=["Stocks"])
async def get_stock_prices(
    symbols: str = Query(..., description="Comma-separated stock symbols")
):
    """
    Get real-time stock prices from Alpaca market data.
    
    Returns current prices, change, and change percent for requested symbols.
    Falls back to mock data if Alpaca is unavailable.
    """
    from backend.services.collectors.alpaca_market import AlpacaMarketDataCollector
    from backend.storage.nasdaq100_tickers import get_nasdaq100_stocks
    from datetime import timedelta
    
    # Parse symbols
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    # Get company names from NASDAQ 100 list
    nasdaq_stocks = get_nasdaq100_stocks(use_api=False)
    name_map = {s["ticker"]: s["name"] for s in nasdaq_stocks}
    
    try:
        collector = AlpacaMarketDataCollector()
        if collector.is_available:
            # Use snapshot API for rich price data including previous close
            snapshots = collector.get_price_snapshots(symbol_list)
            
            result = []
            for sym in symbol_list:
                snap = snapshots.get(sym)
                if snap:
                    result.append(StockPriceInfo(
                        symbol=sym,
                        name=name_map.get(sym, sym),
                        price=snap["price"],
                        change=snap["change"],
                        changePercent=snap["changePercent"],
                        open_price=snap.get("open_price"),
                        high_price=snap.get("high_price"),
                        low_price=snap.get("low_price"),
                        volume=snap.get("volume"),
                        extendedChange=snap.get("extended_change"),
                        extendedChangePercent=snap.get(
                            "extended_change_percent"
                        ),
                    ))
                else:
                    result.append(StockPriceInfo(
                        symbol=sym,
                        name=name_map.get(sym, sym),
                        price=0,
                        change=0,
                        changePercent=0
                    ))
            
            logger.info(f"Returned prices for {len(result)} symbols from Alpaca")
            return result
        else:
            logger.warning(f"Alpaca unavailable: {collector.get_last_error()}")
    except Exception as e:
        logger.error(f"Error fetching stock prices from Alpaca: {e}")
    
    # Fallback: return zero prices (frontend should handle gracefully)
    return [
        StockPriceInfo(
            symbol=sym,
            name=name_map.get(sym, sym),
            price=0,
            change=0,
            changePercent=0
        )
        for sym in symbol_list
    ]


@app.get("/stocks/bars", response_model=HistoricalBarsResponse, tags=["Stocks"])
async def get_stock_bars(
    symbol: str = Query(..., description="Stock ticker symbol"),
    timeframe: str = Query("1Day", description="Timeframe: 1Min, 5Min, 15Min, 1Hour, 1Day"),
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    end_ts: Optional[int] = Query(None, description="End timestamp (Unix seconds) for fetching older data"),
    start_ts: Optional[int] = Query(None, description="Start timestamp (Unix seconds) for fetching older data")
):
    """
    Get historical OHLCV bar data for TradingView-style charts.

    Returns candlestick data from Alpaca for the specified symbol and timeframe.
    Timeframe options: 1Min, 5Min, 15Min, 1Hour, 1Day
    
    For loading more historical data, provide end_ts (and optionally start_ts).
    If end_ts is provided, fetches data ending at that timestamp.
    If start_ts is also provided, fetches data in that specific range.
    """
    import os
    from datetime import timedelta

    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        try:
            from alpaca.data.enums import DataFeed
        except ImportError:
            DataFeed = None  # type: ignore
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="alpaca-py library not installed"
        )

    # Load API keys
    api_key = os.getenv("alpaca-api-key", "").strip().strip("'\"")
    secret_key = os.getenv("alpaca-secret-key", "").strip().strip("'\"")

    if not api_key or not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Alpaca API keys not configured"
        )

    # Import TimeFrameUnit for custom timeframes
    from alpaca.data.timeframe import TimeFrameUnit

    # Map timeframe string to TimeFrame enum
    # Alpaca supports: 1Min-59Min, 1Hour-23Hour, 1Day, 1Week, 1Month
    timeframe_map = {
        "1Min": TimeFrame.Minute,
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame.Hour,
        "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
        "1Day": TimeFrame.Day,
        "1Week": TimeFrame.Week,
    }

    tf = timeframe_map.get(timeframe, TimeFrame.Day)

    try:
        client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)

        # Calculate date range (Yahoo Finance-style).
        # All datetimes must be naive UTC (Alpaca treats naive as UTC).
        #
        # Policy for intraday intervals:
        #   - On a US trading day  → past N×24 hours from now.
        #   - On a non-trading day → end at close of the most recent
        #     trading day; start N days before that.
        # Daily / weekly intervals always use now-based range.

        is_intraday = timeframe in ("1Min", "5Min", "15Min", "30Min",
                                     "1Hour", "4Hour")

        if end_ts is not None:
            # Explicit end timestamp (for loading older data)
            end = datetime.utcfromtimestamp(end_ts)
            if start_ts is not None:
                start = datetime.utcfromtimestamp(start_ts)
            else:
                start = end - timedelta(days=days)
        elif is_intraday:
            # Determine if today is a US trading day (weekday in ET)
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo

            et = ZoneInfo("America/New_York")
            utc = ZoneInfo("UTC")
            now_et = datetime.now(et)

            if now_et.weekday() < 5:
                # Weekday → trading day: past N×24 h
                end = datetime.utcnow()
                start = end - timedelta(days=days)
            else:
                # Weekend → anchor to last Friday's session
                days_since_friday = now_et.weekday() - 4   # Sat=1, Sun=2
                last_fri_et = now_et - timedelta(days=days_since_friday)

                # Cover full extended session: 4 AM → 8 PM ET
                end_et = last_fri_et.replace(
                    hour=20, minute=0, second=0, microsecond=0
                )
                # "1 Day" = show 1 trading day (just Friday),
                # "2 Days" = show 2 days (Thu + Fri), etc.
                start_et = (end_et - timedelta(days=max(days - 1, 0))).replace(
                    hour=4, minute=0, second=0, microsecond=0
                )

                # Convert to naive UTC for Alpaca
                start = start_et.astimezone(utc).replace(tzinfo=None)
                end = end_et.astimezone(utc).replace(tzinfo=None)
        else:
            # Daily / weekly: simple now-based range
            end = datetime.utcnow()
            start = end - timedelta(days=days)

        # Use IEX feed by default: free Alpaca tier does not allow recent SIP data.
        # Set ALPACA_BARS_FEED=sip if you have an Algo Trader Plus (or similar) subscription.
        feed = None
        if DataFeed is not None:
            feed_pref = (os.getenv("ALPACA_BARS_FEED") or "iex").strip().lower()
            if feed_pref == "sip":
                feed = DataFeed.SIP
            else:
                feed = DataFeed.IEX

        request_kw: dict = {
            "symbol_or_symbols": [symbol.upper()],
            "timeframe": tf,
            "start": start,
            "end": end,
        }
        if feed is not None:
            request_kw["feed"] = feed
        request = StockBarsRequest(**request_kw)

        try:
            bars_response = client.get_stock_bars(request)
        except Exception as bars_err:
            err_msg = str(bars_err).lower()
            # Free tier: "subscription does not permit querying recent SIP data"
            if "sip" in err_msg and "subscription" in err_msg and DataFeed is not None and feed != DataFeed.IEX:
                logger.warning("Bars request failed (likely SIP not allowed), retrying with IEX feed: %s", bars_err)
                request_kw["feed"] = DataFeed.IEX
                bars_response = client.get_stock_bars(StockBarsRequest(**request_kw))
            else:
                raise

        symbol_upper = symbol.upper()

        # Extract bars - BarSet may have .data attribute or be dict-like
        bar_list = []
        try:
            # Try accessing via .data attribute first (newer API)
            if hasattr(bars_response, 'data') and bars_response.data:
                data = bars_response.data
                if symbol_upper in data:
                    bar_list = list(data[symbol_upper])
            # Try direct dict-like access with [] operator
            if not bar_list:
                try:
                    bar_list = list(bars_response[symbol_upper])
                except (KeyError, TypeError):
                    pass
            # Try get method if available
            if not bar_list and hasattr(bars_response, 'get'):
                result = bars_response.get(symbol_upper)
                if result:
                    bar_list = list(result)
        except Exception as ex:
            logger.warning(f"Error extracting bars: {ex}")

        if not bar_list:
            logger.info(f"No bars found for {symbol_upper}")
            return HistoricalBarsResponse(
                symbol=symbol_upper,
                bars=[],
                timeframe=timeframe
            )

        bars = []
        for bar in bar_list:
            # Convert timestamp to Unix seconds for lightweight-charts
            ts = bar.timestamp
            if hasattr(ts, 'timestamp'):
                unix_ts = int(ts.timestamp())
            else:
                unix_ts = int(ts)

            bars.append(CandlestickBar(
                time=str(unix_ts),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=int(bar.volume) if bar.volume else None
            ))

        logger.info(f"Returned {len(bars)} bars for {symbol_upper}")
        return HistoricalBarsResponse(
            symbol=symbol_upper,
            bars=bars,
            timeframe=timeframe
        )

    except Exception as e:
        logger.error(f"Error fetching bars for {symbol}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch bar data: {str(e)}"
        )


# ============== Configuration ==============

class ConfigResponse(BaseModel):
    alpha_vantage_configured: bool
    openai_configured: bool
    watchlist_count: int
    data_sources: List[str]


@app.get("/config", response_model=ConfigResponse, tags=["System"])
async def get_config():
    """Get current system configuration status."""
    from backend.config import ALPHA_VANTAGE_API_KEY, OPENAI_API_KEY
    
    data_sources = ["SEC EDGAR (free)", "FRED (free)", "Nasdaq RSS (free)"]
    if ALPHA_VANTAGE_API_KEY:
        data_sources.append("Alpha Vantage (configured)")
    else:
        data_sources.append("Alpha Vantage (mock fallback)")
    
    return ConfigResponse(
        alpha_vantage_configured=bool(ALPHA_VANTAGE_API_KEY),
        openai_configured=bool(OPENAI_API_KEY),
        watchlist_count=len(watchlist_manager.get_symbols()),
        data_sources=data_sources
    )


# Run with: uvicorn backend.main:app --reload  or  python -m backend.main (respects PORT env)
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
