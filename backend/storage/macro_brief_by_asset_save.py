"""
Save operations for per-asset macro brief tables (macro_brief_fx, rates, credit, commodity, equity, policy).
ID: application supplies id via _string_id_to_bigint(macro_brief_asset_string_id / macro_brief_policy_string_id).
"""
import logging
from datetime import date
from typing import Dict, Any, Optional
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.macro_id_utils import (
    _string_id_to_bigint,
    macro_brief_asset_string_id,
    macro_brief_policy_string_id,
)

logger = logging.getLogger(__name__)

ASSET_TABLES = ("fx", "rates", "credit", "commodity", "equity")


def _date_str(d: date) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]


def save_brief_fx(supabase: Client, as_of_date: date, payload: Dict[str, Any]) -> Optional[int]:
    """Upsert one row in macro_brief_fx for as_of_date."""
    if not supabase:
        supabase = get_supabase_client()
    sid = macro_brief_asset_string_id("fx", as_of_date)
    db_id = _string_id_to_bigint(sid)
    row = {
        "id": db_id,
        "as_of_date": _date_str(as_of_date),
        "title": payload.get("title", ""),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
        "sources": payload.get("sources"),
        "coverage_gap": bool(payload.get("coverage_gap", False)),
        "regime": payload.get("regime"),
        "transmission_by_bloc": payload.get("transmission_by_bloc"),
        "relative_value_logic": payload.get("relative_value_logic"),
        "scenario_framework": payload.get("scenario_framework"),
        "trade_relevance": payload.get("trade_relevance"),
    }
    try:
        supabase.table("macro_brief_fx").upsert(row, on_conflict="as_of_date").execute()
        return db_id
    except Exception as e:
        logger.error("Failed to save macro_brief_fx %s: %s", _date_str(as_of_date), e)
        return None


def save_brief_rates(supabase: Client, as_of_date: date, payload: Dict[str, Any]) -> Optional[int]:
    """Upsert one row in macro_brief_rates for as_of_date."""
    if not supabase:
        supabase = get_supabase_client()
    sid = macro_brief_asset_string_id("rates", as_of_date)
    db_id = _string_id_to_bigint(sid)
    row = {
        "id": db_id,
        "as_of_date": _date_str(as_of_date),
        "title": payload.get("title", ""),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
        "sources": payload.get("sources"),
        "coverage_gap": bool(payload.get("coverage_gap", False)),
        "shock_classification": payload.get("shock_classification"),
        "reaction_function": payload.get("reaction_function"),
        "curve_decomposition": payload.get("curve_decomposition"),
        "cross_market_consistency": payload.get("cross_market_consistency"),
        "trade_risk_framing": payload.get("trade_risk_framing"),
    }
    try:
        supabase.table("macro_brief_rates").upsert(row, on_conflict="as_of_date").execute()
        return db_id
    except Exception as e:
        logger.error("Failed to save macro_brief_rates %s: %s", _date_str(as_of_date), e)
        return None


def save_brief_credit(supabase: Client, as_of_date: date, payload: Dict[str, Any]) -> Optional[int]:
    """Upsert one row in macro_brief_credit for as_of_date."""
    if not supabase:
        supabase = get_supabase_client()
    sid = macro_brief_asset_string_id("credit", as_of_date)
    db_id = _string_id_to_bigint(sid)
    row = {
        "id": db_id,
        "as_of_date": _date_str(as_of_date),
        "title": payload.get("title", ""),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
        "sources": payload.get("sources"),
        "coverage_gap": bool(payload.get("coverage_gap", False)),
        "macro_credit_transmission": payload.get("macro_credit_transmission"),
        "spread_decomposition": payload.get("spread_decomposition"),
        "segmentation": payload.get("segmentation"),
        "cross_asset_validation": payload.get("cross_asset_validation"),
        "portfolio_implications": payload.get("portfolio_implications"),
    }
    try:
        supabase.table("macro_brief_credit").upsert(row, on_conflict="as_of_date").execute()
        return db_id
    except Exception as e:
        logger.error("Failed to save macro_brief_credit %s: %s", _date_str(as_of_date), e)
        return None


def save_brief_commodity(supabase: Client, as_of_date: date, payload: Dict[str, Any]) -> Optional[int]:
    """Upsert one row in macro_brief_commodity for as_of_date."""
    if not supabase:
        supabase = get_supabase_client()
    sid = macro_brief_asset_string_id("commodity", as_of_date)
    db_id = _string_id_to_bigint(sid)
    row = {
        "id": db_id,
        "as_of_date": _date_str(as_of_date),
        "title": payload.get("title", ""),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
        "sources": payload.get("sources"),
        "coverage_gap": bool(payload.get("coverage_gap", False)),
        "physical_balance": payload.get("physical_balance"),
        "macro_overlay": payload.get("macro_overlay"),
        "segmentation": payload.get("segmentation"),
        "price_vs_fundamentals": payload.get("price_vs_fundamentals"),
        "scenario_risk": payload.get("scenario_risk"),
    }
    try:
        supabase.table("macro_brief_commodity").upsert(row, on_conflict="as_of_date").execute()
        return db_id
    except Exception as e:
        logger.error("Failed to save macro_brief_commodity %s: %s", _date_str(as_of_date), e)
        return None


def save_brief_equity(supabase: Client, as_of_date: date, payload: Dict[str, Any]) -> Optional[int]:
    """Upsert one row in macro_brief_equity for as_of_date."""
    if not supabase:
        supabase = get_supabase_client()
    sid = macro_brief_asset_string_id("equity", as_of_date)
    db_id = _string_id_to_bigint(sid)
    row = {
        "id": db_id,
        "as_of_date": _date_str(as_of_date),
        "title": payload.get("title", ""),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
        "sources": payload.get("sources"),
        "coverage_gap": bool(payload.get("coverage_gap", False)),
        "impact_decomposition": payload.get("impact_decomposition"),
        "index_vs_factor": payload.get("index_vs_factor"),
        "macro_consistency": payload.get("macro_consistency"),
        "positioning_flows": payload.get("positioning_flows"),
        "actionable_framing": payload.get("actionable_framing"),
    }
    try:
        supabase.table("macro_brief_equity").upsert(row, on_conflict="as_of_date").execute()
        return db_id
    except Exception as e:
        logger.error("Failed to save macro_brief_equity %s: %s", _date_str(as_of_date), e)
        return None


def save_brief_policy(
    supabase: Client,
    as_of_date: date,
    topic: str,
    payload: Dict[str, Any],
) -> Optional[int]:
    """Upsert one row in macro_brief_policy for (as_of_date, topic). topic: Fiscal Policy | Monetary Policy | Trump."""
    if not supabase:
        supabase = get_supabase_client()
    sid = macro_brief_policy_string_id(as_of_date, topic)
    db_id = _string_id_to_bigint(sid)
    row = {
        "id": db_id,
        "as_of_date": _date_str(as_of_date),
        "topic": topic.strip(),
        "title": payload.get("title", ""),
        "summary": payload.get("summary"),
        "summary_bullets": payload.get("summary_bullets"),
        "sources": payload.get("sources"),
        "coverage_gap": bool(payload.get("coverage_gap", False)),
        "mechanism": payload.get("mechanism"),
        "transmission": payload.get("transmission"),
    }
    try:
        supabase.table("macro_brief_policy").upsert(row, on_conflict="as_of_date,topic").execute()
        return db_id
    except Exception as e:
        logger.error("Failed to save macro_brief_policy %s %s: %s", _date_str(as_of_date), topic, e)
        return None


def save_asset_brief(
    supabase: Client,
    asset_key: str,
    as_of_date: date,
    payload: Dict[str, Any],
    topic: Optional[str] = None,
) -> Optional[int]:
    """
    Dispatch save to the correct per-asset table.
    asset_key: fx | rates | credit | commodity | equity | policy.
    For policy, topic must be set (Fiscal Policy | Monetary Policy | Trump).
    """
    if asset_key == "fx":
        return save_brief_fx(supabase, as_of_date, payload)
    if asset_key == "rates":
        return save_brief_rates(supabase, as_of_date, payload)
    if asset_key == "credit":
        return save_brief_credit(supabase, as_of_date, payload)
    if asset_key == "commodity":
        return save_brief_commodity(supabase, as_of_date, payload)
    if asset_key == "equity":
        return save_brief_equity(supabase, as_of_date, payload)
    if asset_key == "policy" and topic:
        return save_brief_policy(supabase, as_of_date, topic, payload)
    logger.warning("Unknown asset_key or missing topic for policy: %s", asset_key)
    return None
