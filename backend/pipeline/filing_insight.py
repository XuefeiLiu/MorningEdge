"""
Filing-in-storyline insight: match storyline (short or long) summary to SEC filing chunks and generate insight.

Triggered when create_storyline returns deserves_filing_story=True (PIPELINE_CREATE_FILING_INSIGHTS).
Single LLM call: decides whether chunks are relevant (useful); if useful, returns answer + citations.
If not useful, no filing storyline is created.

RAG is restricted to the most recent filing per ticker. If story_date is provided and there exists
a filing published between the cited filing date and the story date, we do not create the story.
"""
import json
import logging
import re
from datetime import datetime, timezone
from hashlib import md5
from typing import Any, Dict, List, Optional, Tuple

from supabase import Client
from openai import AsyncOpenAI

from backend.storage.embedding_utils import get_embeddings
from backend.storage.news_articles_save import _string_id_to_bigint
from backend.pipeline.filing_rag import retrieve_similar_filing_chunks
from backend.pipeline.rerank import rerank

logger = logging.getLogger(__name__)


def _parse_filed_date(val: Any) -> Optional[datetime]:
    """Parse filed_date string or value to datetime (UTC)."""
    if not val:
        return None
    try:
        s = str(val)[:10]
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _has_newer_filing_before_story(
    supabase: Client,
    ticker: str,
    max_cited_filed_date: datetime,
    story_date: datetime,
) -> bool:
    """
    Return True if there exists a filing for this ticker with filed_date strictly after
    max_cited_filed_date and on or before story_date. If so, we should not create the filing story.
    """
    ticker_upper = (ticker or "").strip().upper()
    if not ticker_upper:
        return False
    try:
        chunk_result = (
            supabase.table("sec_filing_chunks")
            .select("filing_id")
            .eq("ticker", ticker_upper)
            .execute()
        )
        chunk_data = chunk_result.data or []
        filing_ids = list({r["filing_id"] for r in chunk_data if r.get("filing_id") is not None})
        if not filing_ids:
            return False
        filing_result = (
            supabase.table("sec_filings")
            .select("id, filed_date")
            .in_("id", filing_ids)
            .execute()
        )
        filing_data = filing_result.data or []
        for f in filing_data:
            fd = _parse_filed_date(f.get("filed_date"))
            if fd is None:
                continue
            if max_cited_filed_date < fd <= story_date:
                return True
        return False
    except Exception as e:
        logger.warning(f"Check for newer filing failed: {e}")
        return False

FILING_INSIGHT_TOP_K = 10
FILING_INSIGHT_RERANK_TOP = 5

CHUNK_ID_PREFIX = "filing_"


def _chunk_id(filing_id: Any, chunk_index: Any) -> str:
    """Stable chunk ID for citations, e.g. filing_123_chunk_4."""
    return f"{CHUNK_ID_PREFIX}{filing_id}_chunk_{chunk_index}"


def _parse_filing_date_range(chunks: List[Dict]) -> str:
    """Return a short date range string from chunks' filed_date for prompt."""
    dates = []
    for c in chunks:
        fd = c.get("filed_date")
        if fd:
            dates.append(str(fd)[:10])
    if not dates:
        return "various filing dates"
    dates = sorted(set(dates))
    if len(dates) == 1:
        return dates[0]
    return f"{dates[0]} to {dates[-1]}"


def _normalize_citation_entry(entry: Any) -> Optional[Tuple[str, Optional[str]]]:
    """
    Normalize a citation entry to (chunk_id, summary).
    Entry can be: string (chunk_id), or dict with chunk_id and optional summary.
    Returns (chunk_id, summary) or None if invalid.
    """
    if isinstance(entry, str) and entry.strip():
        return (entry.strip(), None)
    if isinstance(entry, dict) and entry.get("chunk_id"):
        cid = str(entry["chunk_id"]).strip()
        summary = (entry.get("summary") or "").strip() or None
        return (cid, summary) if cid else None
    return None


def _parse_single_llm_response(raw: str) -> Tuple[bool, str, List[Dict[str, Any]], str]:
    """
    Parse single LLM response: expect JSON with useful (bool), and when useful=true:
    answer, citations (list of {chunk_id, summary}), confidence.
    Returns (useful, answer, citations_list, confidence).
    citations_list = [{"chunk_id": "...", "summary": "..." or null}, ...].
    If useful=false or parse fails, returns (False, "", [], "low").
    """
    raw = (raw or "").strip()
    if not raw:
        return False, "", [], "low"
    stripped = re.sub(r"^```(?:json)?\s*", "", raw)
    stripped = re.sub(r"\s*```\s*$", "", stripped).strip()
    for candidate in (stripped, raw):
        try:
            obj = json.loads(candidate)
            if not isinstance(obj, dict):
                continue
            useful = obj.get("useful")
            if useful is False:
                return False, "", [], "low"
            if useful is not True:
                answer_preview = (obj.get("answer") or "").strip()
                if not answer_preview:
                    continue
            answer = (obj.get("answer") or "").strip()
            raw_cits = obj.get("citations")
            citations_list: List[Dict[str, Any]] = []
            if isinstance(raw_cits, list):
                for c in raw_cits:
                    norm = _normalize_citation_entry(c)
                    if norm:
                        cid, summary = norm
                        citations_list.append({"chunk_id": cid, "summary": summary})
            confidence = (obj.get("confidence") or "medium").strip().lower()
            if confidence not in ("high", "medium", "low"):
                confidence = "medium"
            return True, answer or raw, citations_list, confidence
        except (json.JSONDecodeError, TypeError):
            pass
    return False, "", [], "low"


async def create_filing_insight_for_storyline(
    supabase: Client,
    ticker: str,
    source_storyline_id: int,
    summary: str,
    title: str,
    article_id: int,
    contributor_ticker: str,
    llm_client: AsyncOpenAI,
    llm_model: str,
    story_date: Optional[datetime] = None,
    timeline_start: Optional[datetime] = None,
    timeline_end: Optional[datetime] = None,
) -> Optional[int]:
    """
    For a storyline (short or long): embed summary, retrieve similar filing chunks, optionally
    check if producing an insight is useful (LLM), then generate 1-2 sentence insight.
    - Short story: only_most_recent_filing=True; if story_date is set, do not create when a
      newer filing exists between cited filing and story date.
    - Long story: pass timeline_start and timeline_end; consider all chunks for the ticker
      (only_most_recent_filing=False); do not apply the "newer filing exists" check.
    Returns None (no persistence).
    """
    if not summary and not title:
        logger.debug("No summary/title for filing insight, skipping")
        return None
    query_text = (title or "") + " " + (summary or "")[:2000]
    embeddings = await get_embeddings([query_text])
    if embeddings is None or embeddings.size == 0:
        logger.warning("Filing insight: embedding failed, skipping")
        return None
    query_embedding = embeddings[0].tolist()
    use_timeline = timeline_start is not None and timeline_end is not None
    # Short story: only the two most recent sec_filings (by filed_date). Long story: all chunks for ticker.
    chunks = await retrieve_similar_filing_chunks(
        supabase,
        tickers=[ticker.strip().upper()],
        query_embedding=query_embedding,
        limit=FILING_INSIGHT_TOP_K,
        only_most_recent_filing=not use_timeline,
    )
    if not chunks:
        logger.debug(f"No filing chunks for {ticker}, skipping filing insight")
        return None
    # Rerank chunk texts
    chunk_candidates = [{"id": c.get("id"), "title": "", "summary": (c.get("text") or "")[:1500], "published_at": c.get("filed_date")} for c in chunks]
    reranked_list = rerank(query_text, chunk_candidates, min(FILING_INSIGHT_RERANK_TOP, len(chunk_candidates)))
    rid_to_chunk = {c.get("id"): c for c in chunks}
    top_chunks = [rid_to_chunk[r["id"]] for r in reranked_list if isinstance(r, dict) and r.get("id") in rid_to_chunk]
    if not top_chunks:
        top_chunks = chunks[:FILING_INSIGHT_RERANK_TOP]
    date_range_str = _parse_filing_date_range(top_chunks)
    excerpt_parts = []
    for c in top_chunks:
        cid = _chunk_id(c.get("filing_id"), c.get("chunk_index"))
        text = (c.get("text") or "")
        if text:
            excerpt_parts.append(f"[chunk_id: {cid}]\n{text}")
    top_texts = "\n\n---\n\n".join(excerpt_parts)
    if not top_texts:
        return None

    system_content = (
        "You are a financial analyst. You will receive a storyline (title + summary) and SEC filing excerpts. "
        "First decide: are any of these excerpts relevant to the storyline (e.g. risk, business, regulation, 10-K/10-Q)? "
        "If NO: respond with JSON only: {\"useful\": false}. "
        "If YES: respond with JSON: {\"useful\": true, \"answer\": \"1-2 sentence overall insight\", "
        "\"citations\": [{\"chunk_id\": \"filing_X_chunk_Y\", \"summary\": \"One full sentence summarizing or rephrasing this excerpt in plain English.\"}, ...], "
        "\"confidence\": \"high\"|\"medium\"|\"low\"}. "
        "For each cited chunk, provide a \"summary\" that is a single full sentence (not the raw chunk ID): rephrase or summarize what that excerpt says in human-readable form. "
        "One JSON object only, no other text."
    )
    prompt = f"""STORYLINE:
Title: {title or 'N/A'}
Summary: {(summary or '')[:1500]}

SEC FILING EXCERPTS (as of {date_range_str}). Each excerpt is labeled with chunk_id:
{top_texts}

Decide if these excerpts are relevant. If yes: provide a 1-2 sentence overall insight in \"answer\", and for each excerpt you cite include \"chunk_id\" and \"summary\" (one full sentence rephrasing or summarizing that excerpt in plain English—do not repeat the chunk_id as the summary). If no, set useful to false.
Respond with JSON: {{\"useful\": true|false, \"answer\": \"...\", \"citations\": [{{\"chunk_id\": \"filing_X_chunk_Y\", \"summary\": \"Human-readable one sentence for this excerpt.\"}}, ...], \"confidence\": \"high\"|\"medium\"|\"low\"}}."""

    try:
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_completion_tokens=350,
        )
        raw_response = (response.choices[0].message.content or "").strip()
        if not raw_response:
            return None
        useful, answer, citations_list, _confidence = _parse_single_llm_response(raw_response)
        if not useful or not answer:
            logger.debug("Filing insight LLM decided chunks not relevant or no answer, skipping insert")
            return None
        # If story_date is set (short story): do not create when a newer filing exists between cited and story date,
        # and do not cite a filing that is too old relative to the story (e.g. Q3 2025 for a Q1 2026 story).
        # For long story (timeline set) we skip these checks and allow all filings in the timeline.
        if story_date is not None and not use_timeline and top_chunks:
            max_cited = None
            for c in top_chunks:
                fd = _parse_filed_date(c.get("filed_date"))
                if fd is not None and (max_cited is None or fd > max_cited):
                    max_cited = fd
            if max_cited is not None:
                story_dt = story_date if story_date.tzinfo else story_date.replace(tzinfo=timezone.utc)
                if _has_newer_filing_before_story(supabase, ticker, max_cited, story_dt):
                    logger.debug(
                        "Filing insight skipped: a more recent filing exists between cited filing (%s) and story date (%s)",
                        max_cited.date(),
                        story_dt.date(),
                    )
                    return None
                # Don't cite a filing that is too old for the story (e.g. Q3 2025 for Q1 2026 earnings story)
                max_age_days = 180  # ~2 quarters
                delta = (story_dt - max_cited).total_seconds() / 86400.0
                if delta > max_age_days:
                    logger.debug(
                        "Filing insight skipped: cited filing (%s) is too old for story date (%s), delta %.0f days",
                        max_cited.date(),
                        story_dt.date(),
                        delta,
                    )
                    return None
        citations = citations_list
    except Exception as e:
        logger.warning(f"Filing insight LLM failed: {e}")
        return None
    return None
