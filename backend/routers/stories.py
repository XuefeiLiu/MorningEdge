"""Stories endpoints: overnight stories, long stories, discover feed, ask (custom story), filing formatting."""
import asyncio
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.models import (
    OvernightWindowResponse, OvernightStoryResponse, StorylineArticleResponse,
    FilingCitationItem, FormatFilingChunkRequest, FormatFilingChunkResponse,
    StorylineTimelineMonth, StorylineTimelineResponse, LongStoryResponse,
    DiscoverFeedItem, CustomStoryRequest, CustomStoryArticle, CustomStoryResponse,
    MacroSourceItem,
)
from backend.utils.helpers import (
    parse_datetime_param, parse_latest_from_event_time_evidence,
    filing_display_title, looks_like_table, impact_score_to_level,
    sort_key_impact_score, get_overnight_window_ny,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Ask (custom story) concurrency cap; lazy-initialized from ASK_MAX_CONCURRENT
_ask_semaphore: Optional[asyncio.Semaphore] = None


def _get_ask_semaphore() -> Optional[asyncio.Semaphore]:
    global _ask_semaphore
    if _ask_semaphore is None:
        from backend.config import ASK_MAX_CONCURRENT
        _ask_semaphore = asyncio.Semaphore(ASK_MAX_CONCURRENT) if ASK_MAX_CONCURRENT > 0 else None
    return _ask_semaphore


# ============== Overnight Window ==============

@router.get("/overnight-window", response_model=OvernightWindowResponse, tags=["Overnight Stories"])
async def get_overnight_window():
    """Return the current overnight session boundaries."""
    start_utc, end_utc = get_overnight_window_ny()
    return OvernightWindowResponse(start=start_utc.isoformat(), end=end_utc.isoformat())


# ============== Overnight Stories ==============

@router.get("/overnight-stories", response_model=List[OvernightStoryResponse], tags=["Overnight Stories"])
async def get_overnight_stories(
    ticker: str = Query(..., description="Stock ticker symbol"),
    start_date: Optional[str] = Query(None, description="Start date ISO8601 (inclusive)"),
    end_date: Optional[str] = Query(None, description="End date ISO8601 (inclusive)"),
):
    """List overnight pipeline stories for a ticker."""
    from backend.storage.supabase_client import get_supabase_client
    try:
        supabase = get_supabase_client()
        t = ticker.strip().upper()
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
        start_dt = parse_datetime_param(start_date)
        end_dt = parse_datetime_param(end_date)
        if not rows:
            return []
        out: List[OvernightStoryResponse] = []
        for r in rows:
            evidence = r.get("event_time_evidence")
            event_time = parse_latest_from_event_time_evidence(evidence)
            if event_time is None:
                continue
            if start_dt is not None and event_time < start_dt:
                continue
            if end_dt is not None and event_time > end_dt:
                continue
            asof = r.get("asof_date")
            if asof and hasattr(asof, "isoformat"):
                asof_str = asof.isoformat()[:10]
            else:
                asof_str = str(asof)[:10] if asof else ""
            risk_drivers = r.get("risk_drivers")
            if risk_drivers is not None and not isinstance(risk_drivers, list):
                risk_drivers = []
            out.append(OvernightStoryResponse(
                id=str(r["id"]),
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
        _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        out.sort(key=lambda x: (x.latest_article_published_at or _epoch), reverse=True)
        return out
    except Exception as e:
        logger.error("Error fetching overnight stories for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overnight-stories/{story_id}/articles", response_model=List[StorylineArticleResponse], tags=["Overnight Stories"])
async def get_overnight_story_articles(story_id: str):
    """List articles linked to an overnight story."""
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
            out.append(StorylineArticleResponse(
                id=aid, ticker=a.get("ticker") or "", title=a.get("title") or "",
                summary=a.get("summary"), url=a.get("url"), source=a.get("source"),
                published_at=a.get("published_at"), relation_type=link_map.get(aid),
            ))
        out.sort(key=lambda x: (x.published_at or datetime.min), reverse=True)
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching overnight story articles for %s: %s", story_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overnight-stories/{story_id}/filing-chunks", response_model=List[FilingCitationItem], tags=["Overnight Stories"])
async def get_overnight_story_filing_chunks(story_id: str):
    """Return SEC filing chunk(s) linked to an overnight story."""
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
        title = filing_display_title(form_type, filed_date, fiscal_year, period)
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
        is_table = looks_like_table(chunk_text)
        return [FilingCitationItem(
            chunk_id=str(top_chunk_id), filing_title=title, summary=None,
            text=chunk_text, filing_url=filing_url, form_type=form_type,
            filed_date=filed_date, is_table=is_table,
        )]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching overnight story filing chunks for %s: %s", story_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ============== Filing Formatting ==============

@router.post("/storylines/format-filing-chunk", response_model=FormatFilingChunkResponse, tags=["Storylines"])
async def format_filing_chunk(request: FormatFilingChunkRequest):
    """Convert raw SEC filing chunk text to human-readable format using LLM."""
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
    user_content = f"Format this SEC filing excerpt into human-readable form (markdown table if tabular, clear paragraphs if prose):\n\n{raw[:12000]}"
    try:
        if not OPENAI_API_KEY:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system_content}, {"role": "user", "content": user_content}],
            temperature=0.2, max_tokens=2000,
        )
        formatted = (response.choices[0].message.content or "").strip()
        if not formatted:
            formatted = raw
        return FormatFilingChunkResponse(formatted=formatted)
    except Exception as e:
        logger.error(f"Format filing chunk LLM failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to format chunk")


# ============== Long Stories ==============

@router.get("/long-stories", response_model=List[LongStoryResponse], tags=["Long Stories"])
async def get_long_stories(ticker: str = Query(..., description="Stock ticker symbol")):
    """List all long stories for a ticker."""
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
                id=str(r["id"]), ticker=r["ticker"], title=r.get("title"),
                canonical_theme=r.get("canonical_theme"), summary=r.get("summary"),
                impact_level=r.get("impact_level"), article_count=count_by_id.get(r["id"], 0),
                created_at=r.get("created_at"), last_updated_at=r.get("last_updated_at"),
                latest_article_published_at=latest_article_by_story.get(r["id"]),
            )
            for r in rows
        ]
    except Exception as e:
        if "does not exist" in str(e).lower():
            return []
        logger.error("Error fetching long stories for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/long-stories/{long_story_id}/timeline", response_model=StorylineTimelineResponse, tags=["Long Stories"])
async def get_long_story_timeline(long_story_id: str):
    """Returns articles linked to a long story grouped by month."""
    from backend.storage.supabase_client import get_supabase_client
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
        title = summary = theme = None
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
            by_month[month_key].append(StorylineArticleResponse(
                id=a.get("id"), ticker=a.get("ticker") or "", title=a.get("title") or "",
                summary=a.get("summary"), url=a.get("url"), source=a.get("source"),
                published_at=a.get("published_at"), relation_type=link_map.get(a.get("id")),
            ))
        for month_key in by_month:
            by_month[month_key].sort(key=lambda x: (x.published_at or datetime.min), reverse=True)
        months_sorted = sorted(by_month.keys(), reverse=True)
        return StorylineTimelineResponse(
            title=title, summary=summary, theme=theme,
            total_articles=len(articles),
            months=[StorylineTimelineMonth(month=m, articles=by_month[m]) for m in months_sorted],
        )
    except Exception as e:
        if "does not exist" in str(e).lower():
            raise HTTPException(status_code=404, detail="Long story or table not found")
        logger.error("Error fetching long story timeline for %s: %s", long_story_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ============== Discover Feed ==============

@router.get("/discover/feed", response_model=List[DiscoverFeedItem], tags=["Discover"])
async def get_discover_feed(
    short_limit: int = Query(20, ge=1, le=50),
    long_days: int = Query(7, ge=1, le=30),
    top: int = Query(10, ge=1, le=30),
):
    """Feed for Discover tab: most impactful storylines and long stories."""
    from backend.storage.supabase_client import get_supabase_client
    from backend.storage.stocks_query import get_stocks
    try:
        supabase = get_supabase_client()
        cutoff = (datetime.utcnow() - timedelta(days=long_days)).isoformat()
        items: List[Dict[str, Any]] = []
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
                impact_rating = impact_score_to_level(score) if score is not None else ((r.get("impact_level") or "").strip().lower() or "medium")
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
        items.sort(key=lambda x: (x.get("last_updated_at") or ""), reverse=True)
        items.sort(key=sort_key_impact_score)
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
        return [
            DiscoverFeedItem(
                ticker=x["ticker"], name=name_by_ticker.get(x["ticker"], x["ticker"]),
                price=0.0, change_percent=0.0, headline=x["headline"],
                impact_rating=x.get("impact_rating"), story_type=x["story_type"],
                storyline_id=x.get("storyline_id"), long_story_id=x.get("long_story_id"),
                last_updated_at=x.get("last_updated_at"), chart_data=None,
            )
            for x in items
        ]
    except Exception as e:
        logger.error("Error fetching discover feed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============== Ask (Custom Story) ==============

@router.post("/storylines/custom", response_model=CustomStoryResponse, tags=["Storylines"])
async def create_custom_story(request: CustomStoryRequest, http_request: Request):
    """User-created story: answer a question using relevant articles."""
    from backend.services.ask_limits import check_ask_limits
    client_ip = http_request.client.host if http_request.client else "unknown"
    limited = await check_ask_limits(client_ip)
    if limited:
        retry_after, detail = limited
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(retry_after)})
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

    if not tickers_list:
        if len(question) > CUSTOM_STORY_QUERY_MAX_CHARS:
            raise HTTPException(status_code=400, detail=f"Question exceeds max length ({CUSTOM_STORY_QUERY_MAX_CHARS} chars). Shorten your question.")
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
                    topic_name = b.get("topic") or ""
                    title = b.get("title") or ""
                    summary = (b.get("summary") or "")[:max_brief_chars]
                    block = f"[{as_of.isoformat()}] {topic_name}: {title}\n{summary}\n"
                    if total_context_chars + len(block) > max_total:
                        continue
                    macro_context_parts.append(block)
                    total_context_chars += len(block)
                    macro_sources_list.append(MacroSourceItem(topic=topic_name, title=title or None, as_of_date=as_of.isoformat()))
            macro_context = "\n".join(macro_context_parts) if macro_context_parts else "No macro briefs available for the past week."
            current_prompt = f'The user asked: "{question}"\n\nRelevant macro briefs (for context):\n{macro_context}\n\nWrite a concise answer (2–4 paragraphs) using these macro briefs. If there is little relevant content, say so briefly.'
            _history = (request.history or [])[:6]
            history_entries = [h for h in _history if h.role in ("user", "assistant") and (h.content or "").strip()]
            messages = [{"role": "system", "content": "You are a macro analyst. Answer using the provided macro briefs. Be concise and factual. Use previous conversation context when the user asks a follow-up."}]
            for h in history_entries:
                messages.append({"role": h.role, "content": (h.content or "").strip()[:2000]})
            messages.append({"role": "user", "content": current_prompt})
            max_tokens = max(100, min(CUSTOM_STORY_MAX_TOKENS, 2000))
            try:
                response = await client.chat.completions.create(model=model, messages=messages, temperature=0.5, max_tokens=max_tokens)
                answer = (response.choices[0].message.content or "").strip()
            except Exception as e:
                logger.error(f"Ask macro LLM failed: {e}")
                answer = "Unable to generate an answer from macro briefs at this time."
            await record_ask(client_ip)
            return CustomStoryResponse(answer=answer, articles=[], context_type="macro", macro_sources=macro_sources_list[:20], detected_tickers=[])

        if not tickers_list:
            await record_ask(client_ip)
            return CustomStoryResponse(
                answer="I couldn't identify specific tickers or a macro focus from your question. Try mentioning company names (e.g. Apple, Tesla) or macro topics (e.g. Fed, rates, inflation).",
                articles=[], context_type="stock", detected_tickers=[],
            )

    if len(question) > CUSTOM_STORY_QUERY_MAX_CHARS:
        raise HTTPException(status_code=400, detail=f"Question exceeds max length ({CUSTOM_STORY_QUERY_MAX_CHARS} chars). Shorten your question.")
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
    rag_start_date = datetime.now(timezone.utc) - timedelta(days=183)
    similar = await retrieve_similar_news(
        supabase, tickers_list, query_embedding, exclude_article_ids=None,
        limit=min(RAG_TOP_K_CANDIDATES, 30), start_date=rag_start_date,
    )
    top_n = 10
    reranked = rerank(question, similar, top_n) if similar else []
    articles_for_llm = reranked
    primary_ticker = tickers_list[0]
    article_list = [
        CustomStoryArticle(
            id=a.get("id"), ticker=a.get("ticker") or primary_ticker,
            title=a.get("title") or "", summary=a.get("summary"),
            url=a.get("url"), source=a.get("source"), published_at=a.get("published_at"),
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
    current_prompt = f'The user asked: "{question}"\n\nRelevant news articles (for context):\n{context}\n\nWrite a concise, historically-grounded answer (2–4 paragraphs) that uses these articles to address the question.{relationship_instruction} Do not list articles; weave the narrative. If there is little relevant content, say so briefly.'
    _history = (request.history or [])[:6]
    history_entries = [h for h in _history if h.role in ("user", "assistant") and (h.content or "").strip()]
    messages = [{"role": "system", "content": "You are a financial news analyst. Answer the user's question using the provided articles. Be concise and factual. Use previous conversation context when the user asks a follow-up."}]
    for h in history_entries:
        messages.append({"role": h.role, "content": (h.content or "").strip()[:2000]})
    messages.append({"role": "user", "content": current_prompt})
    max_tokens = max(100, min(CUSTOM_STORY_MAX_TOKENS, 2000))
    try:
        response = await _client.chat.completions.create(model=_model, messages=messages, temperature=0.5, max_tokens=max_tokens)
        answer = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"Custom story LLM failed: {e}")
        answer = "Unable to generate an answer at this time. Here are the most relevant articles."
    await record_ask(client_ip)
    return CustomStoryResponse(answer=answer, articles=article_list, context_type="stock", detected_tickers=tickers_list)
