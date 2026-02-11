"""
Daily summary of summaries: take all 8 topic briefs (FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy, Monetary Policy, Trump)
for a date, call LLM to produce one daily macro summary, and save to macro_daily_summary table.
Run after synthesize_all_topics for the same date.
"""
import asyncio
import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from backend.config import OPENAI_API_KEY, OPENAI_MODEL
from backend.macro.prompts import DAILY_SUMMARY_SYSTEM, build_daily_summary_user
from backend.storage.macro_brief_by_asset_query import get_all_briefs_for_date
from backend.storage.macro_daily_summary_save import save_daily_summary
from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _get_llm_client_and_model(provider: Optional[str] = None) -> tuple:
    """Return (AsyncOpenAI client, model name). OpenAI only."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return client, OPENAI_MODEL


def _parse_daily_summary_response(content: str) -> Optional[Dict[str, Any]]:
    """Parse LLM JSON response; strip markdown code block if present."""
    if not content or not content.strip():
        return None
    text = content.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Daily summary JSON parse failed: %s", e)
        return None


def _fallback_payload(date_str: str) -> Dict[str, Any]:
    """Minimal payload when LLM fails or no briefs."""
    return {
        "title": f"Daily Macro Summary — {date_str}",
        "summary": "No consolidated summary available for this date.",
        "summary_bullets": [],
    }


async def synthesize_daily_summary(
    as_of_date: date,
    supabase=None,
    llm_client: Optional[AsyncOpenAI] = None,
    llm_model: Optional[str] = None,
) -> Optional[int]:
    """
    Load all 8 topic briefs for as_of_date, call LLM to produce one daily summary, save to macro_daily_summary.
    Returns saved row id or None. Run after synthesize_all_topics for the same date.
    """
    if supabase is None:
        supabase = get_supabase_client()
    date_str = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]

    briefs = get_all_briefs_for_date(supabase, as_of_date, topic=None, full=False)
    if not briefs:
        payload = _fallback_payload(date_str)
        return save_daily_summary(supabase, as_of_date, payload)

    if llm_client is None or llm_model is None:
        try:
            llm_client, llm_model = _get_llm_client_and_model()
        except ValueError as e:
            logger.warning("Daily summary LLM not configured: %s", e)
            payload = _fallback_payload(date_str)
            return save_daily_summary(supabase, as_of_date, payload)

    user_msg = build_daily_summary_user(date_str, briefs)
    try:
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": DAILY_SUMMARY_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
        )
        choice = response.choices[0] if response.choices else None
        if not choice or not getattr(choice, "message", None):
            payload = _fallback_payload(date_str)
            return save_daily_summary(supabase, as_of_date, payload)
        content = choice.message.content
        payload = _parse_daily_summary_response(content)
        if not payload:
            payload = _fallback_payload(date_str)
        else:
            payload.setdefault("title", f"Daily Macro Summary — {date_str}")
            payload.setdefault("summary", "")
            payload.setdefault("summary_bullets", [])
        return save_daily_summary(supabase, as_of_date, payload)
    except Exception as e:
        logger.exception("Daily summary LLM failed for %s: %s", date_str, e)
        payload = _fallback_payload(date_str)
        return save_daily_summary(supabase, as_of_date, payload)


def run_synthesize_daily_summary_sync(as_of_date: date, supabase=None, **kwargs) -> Optional[int]:
    """Synchronous entry point for pipeline or backfill."""
    return asyncio.run(synthesize_daily_summary(as_of_date, supabase=supabase, **kwargs))
