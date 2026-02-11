"""
Per-topic analyst report synthesis: one LLM call per topic (8 total), write to per-asset brief tables.
Reads raw items from macro_raw_items (single table); optionally includes cross-topic items for cross-impact.
Uses prompt_demo-aligned per-asset system + user prompts; saves to macro_brief_fx, macro_brief_rates, etc., and macro_brief_policy.
"""
import asyncio
import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from backend.config import (
    MACRO_KB_BRIEF_TOP_K,
    MACRO_KB_RETRIEVAL_TOP_K,
    MACRO_RAW_MIN_RELEVANCE,
    MACRO_TOPICS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from backend.macro.prompts import get_synthesis_system, build_synthesis_user
from backend.macro.kb_retrieval import retrieve_chunks_async
from backend.storage.macro_brief_by_asset_save import save_asset_brief
from backend.storage.macro_raw_items_query import get_raw_items_for_date, get_raw_items_for_date_primary_plus_cross
from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# Max raw items per topic; cross-topic items for cross-impact (per other topic)
SYNTHESIS_ITEMS_PER_TOPIC = 20
SYNTHESIS_CROSS_TOPIC_PER_TOPIC = 3

# Topic -> asset_key for save (fx, rates, credit, commodity, equity, policy)
TOPIC_TO_ASSET_KEY: Dict[str, str] = {
    "FX": "fx",
    "RATE": "rates",
    "CREDIT": "credit",
    "COMMODITY": "commodity",
    "EQUITY": "equity",
    "Fiscal Policy": "policy",
    "Monetary Policy": "policy",
    "Trump": "policy",
}


def _get_llm_client_and_model(provider: Optional[str] = None):
    """Return (AsyncOpenAI client, model name). OpenAI only."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return client, OPENAI_MODEL


def _items_for_llm(items: List[Dict]) -> List[Dict]:
    """Reduce raw items to fields needed for prompt (title, summary, url, source, published_at)."""
    out = []
    for it in items:
        out.append({
            "title": it.get("title"),
            "summary": it.get("summary"),
            "url": it.get("url"),
            "source": it.get("source"),
            "published_at": it.get("published_at"),
        })
    return out


def _format_kb_excerpts(chunks: List[Dict]) -> str:
    """Format macro KB chunks as text with optional page citation (for synthesis user message)."""
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        text = c.get("text") or ""
        page_start = c.get("page_start")
        page_end = c.get("page_end")
        cite = f" [p.{page_start}-{page_end}]" if page_start is not None else ""
        parts.append(f"---{cite}\n{text}")
    return "\n\n".join(parts)


def _items_to_query_text(topic: str, date_str: str, items: List[Dict], max_chars: int = 1200) -> str:
    """Build query string for KB retrieval from topic, date, and item titles/summaries."""
    parts = [f"{topic} {date_str}"]
    for it in items[:15]:
        title = (it.get("title") or "").strip()
        summary = (it.get("summary") or "").strip()
        if title:
            parts.append(title)
        if summary and summary != title:
            parts.append(summary)
    combined = " ".join(parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "…"
    return combined


def _parse_synthesis_response(content: str) -> Optional[Dict[str, Any]]:
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
        logger.warning("Synthesis JSON parse failed: %s", e)
        return None


def _fallback_payload(topic: str, date_str: str, asset_key: str) -> Dict[str, Any]:
    """Minimal payload when no items or LLM fails: coverage_gap true. Shape matches target table."""
    common = {
        "title": f"{topic}-{date_str}",
        "summary": "No major confirmed developments found in collected sources today.",
        "summary_bullets": ["No major confirmed developments found in collected sources today."],
        "sources": [],
        "coverage_gap": True,
    }
    if asset_key == "policy":
        return {**common, "mechanism": None, "transmission": None}
    # Asset tables: add null for asset-specific columns (save layer uses .get())
    if asset_key == "fx":
        return {**common, "regime": None, "transmission_by_bloc": None, "relative_value_logic": None, "scenario_framework": None, "trade_relevance": None}
    if asset_key == "rates":
        return {**common, "shock_classification": None, "reaction_function": None, "curve_decomposition": None, "cross_market_consistency": None, "trade_risk_framing": None}
    if asset_key == "credit":
        return {**common, "macro_credit_transmission": None, "spread_decomposition": None, "segmentation": None, "cross_asset_validation": None, "portfolio_implications": None}
    if asset_key == "commodity":
        return {**common, "physical_balance": None, "macro_overlay": None, "segmentation": None, "price_vs_fundamentals": None, "scenario_risk": None}
    if asset_key == "equity":
        return {**common, "impact_decomposition": None, "index_vs_factor": None, "macro_consistency": None, "positioning_flows": None, "actionable_framing": None}
    return common


async def synthesize_one_topic(
    supabase,
    as_of_date: date,
    topic: str,
    llm_client: AsyncOpenAI,
    llm_model: str,
    use_cross_topic: bool = True,
) -> Optional[int]:
    """
    Load raw items for topic from macro_raw_items (primary + optional cross-topic), one LLM call, parse and save to per-asset brief table. Returns brief id or None.
    """
    date_str = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    asset_key = TOPIC_TO_ASSET_KEY.get(topic, "policy")
    min_relevance = MACRO_RAW_MIN_RELEVANCE if (MACRO_RAW_MIN_RELEVANCE or 0) > 0 else None
    if use_cross_topic and asset_key != "policy":
        items = get_raw_items_for_date_primary_plus_cross(
            supabase, as_of_date, primary_topic=topic,
            primary_limit=SYNTHESIS_ITEMS_PER_TOPIC,
            cross_limit_per_topic=SYNTHESIS_CROSS_TOPIC_PER_TOPIC,
            min_relevance=min_relevance,
        )
    else:
        items = get_raw_items_for_date(supabase, as_of_date, topic=topic, limit=SYNTHESIS_ITEMS_PER_TOPIC, min_relevance=min_relevance)
    if not items:
        payload = _fallback_payload(topic, date_str, asset_key)
        payload["title"] = f"{topic}-{date_str}"
        return save_asset_brief(supabase, asset_key, as_of_date, payload, topic=topic if asset_key == "policy" else None)

    kb_excerpts = ""
    if MACRO_KB_BRIEF_TOP_K > 0:
        try:
            query_text = _items_to_query_text(topic, date_str, items)
            chunks = await retrieve_chunks_async(
                query_text,
                supabase=supabase,
                top_k=MACRO_KB_RETRIEVAL_TOP_K,
                rerank_top=MACRO_KB_BRIEF_TOP_K,
            )
            kb_excerpts = _format_kb_excerpts(chunks)
        except Exception as e:
            logger.warning("KB retrieval for synthesis topic %s failed: %s", topic, e)

    user_msg = build_synthesis_user(topic, date_str, _items_for_llm(items), kb_excerpts=kb_excerpts)
    system_prompt = get_synthesis_system(topic)
    try:
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
        )
        choice = response.choices[0] if response.choices else None
        if not choice or not getattr(choice, "message", None):
            payload = _fallback_payload(topic, date_str, asset_key)
            payload["title"] = f"{topic}-{date_str}"
            return save_asset_brief(supabase, asset_key, as_of_date, payload, topic=topic if asset_key == "policy" else None)
        content = choice.message.content
        payload = _parse_synthesis_response(content)
        if not payload:
            payload = _fallback_payload(topic, date_str, asset_key)
        else:
            payload.setdefault("coverage_gap", False)
            payload.setdefault("sources", [])
        payload["title"] = f"{topic}-{date_str}"
        return save_asset_brief(supabase, asset_key, as_of_date, payload, topic=topic if asset_key == "policy" else None)
    except Exception as e:
        logger.exception("Synthesis LLM failed for topic %s: %s", topic, e)
        payload = _fallback_payload(topic, date_str, asset_key)
        payload["title"] = f"{topic}-{date_str}"
        return save_asset_brief(supabase, asset_key, as_of_date, payload, topic=topic if asset_key == "policy" else None)


async def synthesize_all_topics(
    as_of_date: date,
    supabase=None,
    llm_client: Optional[AsyncOpenAI] = None,
    llm_model: Optional[str] = None,
    use_cross_topic: bool = True,
) -> int:
    """
    Run one LLM call per topic (8 total), save each to per-asset brief tables (macro_brief_fx, ..., macro_brief_policy). Returns count saved.
    """
    if supabase is None:
        supabase = get_supabase_client()
    if llm_client is None or llm_model is None:
        llm_client, llm_model = _get_llm_client_and_model()
    count = 0
    total = len(MACRO_TOPICS)
    for idx, topic in enumerate(MACRO_TOPICS):
        print(f"[macro digest] Synthesizing {idx + 1}/{total}: {topic}...", flush=True)
        logger.info("Synthesizing topic %d/%d: %s", idx + 1, total, topic)
        try:
            bid = await synthesize_one_topic(supabase, as_of_date, topic, llm_client, llm_model, use_cross_topic=use_cross_topic)
            if bid is not None:
                count += 1
                logger.info("Saved brief for %s", topic)
        except Exception as e:
            logger.exception("Synthesis failed for topic %s: %s", topic, e)
    print(f"[macro digest] Synthesis done: {count}/{total} briefs saved", flush=True)
    logger.info("Synthesis complete: %d/%d briefs saved", count, total)
    return count


def run_synthesis_sync(as_of_date: date, **kwargs) -> int:
    """Synchronous entry point."""
    return asyncio.run(synthesize_all_topics(as_of_date, **kwargs))
