"""
On-demand macro impact: load 8 briefs, retrieve macro_kb_chunks, one LLM call, write macro_daily_impact_reports.
Factor mapping, factor_impacts, report_markdown, signals.
"""
import asyncio
import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from backend.config import (
    MACRO_KB_RERANK_TOP_K,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from backend.macro.kb_retrieval import retrieve_chunks_async
from backend.macro.prompts import IMPACT_SYSTEM, build_impact_user
from backend.storage.macro_brief_by_asset_query import get_all_briefs_for_date
from backend.storage.macro_impact_reports_save import save_impact_report
from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _get_llm_client_and_model(provider: Optional[str] = None):
    """Return (AsyncOpenAI client, model name). OpenAI only."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return client, OPENAI_MODEL


def _format_excerpts(chunks: List[Dict]) -> str:
    """Format KB chunks as text with optional page citation."""
    parts = []
    for c in chunks:
        text = c.get("text") or ""
        page_start = c.get("page_start")
        page_end = c.get("page_end")
        cite = f" [p.{page_start}-{page_end}]" if page_start is not None else ""
        parts.append(f"---{cite}\n{text}")
    return "\n\n".join(parts)


def _briefs_to_query_text(briefs: List[Dict]) -> str:
    """Concatenate brief summaries and key fields (mechanism, transmission, regime, etc.) for retrieval query."""
    parts = []
    for b in briefs:
        topic = b.get("topic", "")
        summary = b.get("summary") or ""
        # Policy briefs: mechanism, transmission; asset briefs: regime, transmission_by_bloc, scenario_framework, etc.
        extra = []
        for k in ("mechanism", "transmission", "regime", "relative_value_logic", "scenario_framework", "shock_classification", "curve_decomposition", "macro_credit_transmission", "physical_balance", "impact_decomposition"):
            v = b.get(k)
            if v is not None:
                extra.append(str(v) if not isinstance(v, dict) else json.dumps(v))
        parts.append(f"[{topic}] {summary} " + " ".join(extra))
    return " ".join(parts)


def _parse_impact_response(content: str) -> Optional[Dict[str, Any]]:
    """Parse LLM JSON; strip markdown code block if present."""
    if not content or not content.strip():
        return None
    text = content.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Impact JSON parse failed: %s", e)
        return None


async def generate_impact_report(
    as_of_date: date,
    supabase=None,
    portfolio: Optional[Dict[str, Any]] = None,
    portfolio_id: Optional[str] = None,
    llm_client: Optional[AsyncOpenAI] = None,
    llm_model: Optional[str] = None,
) -> Optional[int]:
    """
    Load 8 briefs for date, retrieve macro_kb_chunks, one LLM call, save to macro_daily_impact_reports.
    Returns report id or None.
    """
    if supabase is None:
        supabase = get_supabase_client()
    date_str = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    briefs = get_all_briefs_for_date(supabase, as_of_date, full=True)
    if not briefs:
        logger.warning("No briefs for %s; cannot generate impact", date_str)
        return None
    query_text = _briefs_to_query_text(briefs)
    chunks = await retrieve_chunks_async(
        query_text, supabase=supabase, rerank_top=MACRO_KB_RERANK_TOP_K
    )
    excerpts = _format_excerpts(chunks)
    briefs_json = json.dumps(briefs, default=str)
    portfolio_str = json.dumps(portfolio or {}, default=str)
    user_msg = build_impact_user(date_str, briefs_json, excerpts, portfolio=portfolio_str)
    if llm_client is None or llm_model is None:
        llm_client, llm_model = _get_llm_client_and_model()
    try:
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": IMPACT_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
        )
        choice = response.choices[0] if response.choices else None
        if not choice or not getattr(choice, "message", None):
            return None
        payload = _parse_impact_response(choice.message.content)
        if not payload:
            return None
        return save_impact_report(
            supabase,
            as_of_date,
            {
                "topics": payload.get("topics"),
                "report_markdown": payload.get("report_markdown"),
                "signals": payload.get("signals"),
                "factor_mapping": payload.get("factor_mapping"),
                "factor_impacts": payload.get("factor_impacts"),
            },
            portfolio_id=portfolio_id,
        )
    except Exception as e:
        logger.exception("Impact LLM failed: %s", e)
        return None


def run_impact_sync(
    as_of_date: date,
    portfolio: Optional[Dict[str, Any]] = None,
    portfolio_id: Optional[str] = None,
    **kwargs,
) -> Optional[int]:
    """Synchronous entry point."""
    return asyncio.run(generate_impact_report(as_of_date, portfolio=portfolio, portfolio_id=portfolio_id, **kwargs))
