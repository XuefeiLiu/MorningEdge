"""
One LLM call per story cluster: build prompt, call OpenAI, parse strict JSON into story dict.
Session rule: if latest published_at in ET is 9:00am–4:00pm on a US business day → INTRADAY (rule-based).
Otherwise we use the LLM: after 4pm ET on a business day, or any time on weekend/holiday (OVERNIGHT = new
weekend/holiday news, INTRADAY = recap of weekday news).
"""
import json
import logging
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from backend.pipeline.overnight_pipeline.config import OVERNIGHT_LLM_MODEL, PROMPT_VERSION
from backend.utils.us_business_day import is_us_business_day

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

SYSTEM = """You are a financial news analyst. Return only a valid JSON object. No markdown, no explanation.
Classify session_label: when articles are published after 4:00 PM ET on a business day, or on a weekend/holiday, use event time when evident; late recaps of intraday events → INTRADAY; genuinely new weekend/holiday news → OVERNIGHT.
Use escaped quotes (\\") inside string values; no raw newlines inside strings."""

STORY_JSON_SCHEMA = """
Return a single JSON object with these keys (all required unless noted):
- "title": A short, news-style headline that includes basic entity names (e.g. company name or ticker when relevant). Like a news title: 3–10 words, concrete and recognizable (e.g. "Apple Beats Earnings, Raises Guidance" or "Tesla Recalls Over Software Bug"). Include the main company/entity so readers know what the story is about.
- "summary": 120-180 word storyline summary (string)
- "topics": array of topic strings
- "session_label": one of "OVERNIGHT", "INTRADAY", "MIXED", "UNKNOWN" (on business days 9am-4pm ET overridden by rule; after 4pm ET or on weekend/holiday use your judgment: recap of weekday news → INTRADAY, new weekend/holiday news → OVERNIGHT)
- "session_confidence": number 0-1
- "event_time_evidence": array of strings (cues from sources)
- "risk_horizon": e.g. "next_open_to_10am_ET" (string)
- "prob_move_ge_1pct": number 0-1
- "prob_move_ge_2pct": number 0-1
- "expected_abs_move_pct": number (e.g. 1.5)
- "direction_bias": one of "UP", "DOWN", "NEUTRAL", "MIXED"
- "risk_confidence": number 0-1
- "risk_drivers": array of strings
- "risk_caveats": array of strings
- "is_filing_related": boolean
- "filing_form_types": array of strings (e.g. ["10-Q"]) or []
- "estimated_filing_date_et": date string YYYY-MM-DD or null
- "filing_signals": array of strings
"""


def _build_cluster_prompt(
    ticker: Optional[str],
    anchor_title: Optional[str],
    anchor_summary: Optional[str],
    articles: List[Dict],
    asof_date: date,
) -> str:
    parts = [f"Date (ET): {asof_date.isoformat()}\n"]
    if ticker:
        parts.append(
            f"Ticker (target stock for this story): {ticker.upper()}. "
            "If the member articles are NOT meaningfully related to this ticker for today's story "
            "(e.g. they are about other companies, or the cluster is noise), return only: {\"omit_story\": true}. "
            "Otherwise return a full story object and do not include omit_story.\n"
        )
    if anchor_title or anchor_summary:
        parts.append("Anchor (framing only):")
        if anchor_title:
            parts.append(f"  Title: {anchor_title}")
        if anchor_summary:
            lead = (anchor_summary or "")
            parts.append(f"  Lead: {lead}")
        parts.append("")
    parts.append("Member articles:")
    for a in articles:
        source = a.get("source") or ""
        pub = a.get("published_at") or ""
        headline = (a.get("title") or "").strip()
        lead = (a.get("summary") or "")
        parts.append(f"- source={source}, published_at={pub}")
        parts.append(f"  headline: {headline}")
        parts.append(f"  lead: {lead}")
        parts.append("")
    parts.append(STORY_JSON_SCHEMA)
    return "\n".join(parts)


def _parse_published_at_utc(value: Any) -> Optional[datetime]:
    """Parse published_at (UTC) from article dict. Returns timezone-aware UTC datetime or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _latest_published_at_et(articles: List[Dict]) -> Optional[datetime]:
    """Latest published_at among articles, converted to ET. published_at is UTC."""
    latest_utc: Optional[datetime] = None
    for a in articles:
        dt = _parse_published_at_utc(a.get("published_at"))
        if dt is not None and (latest_utc is None or dt > latest_utc):
            latest_utc = dt
    if latest_utc is None:
        return None
    return latest_utc.astimezone(ET)


def _is_intraday_by_time(articles: List[Dict]) -> bool:
    """
    True if the latest article published_at (UTC) in New York is within 9:00 AM–4:00 PM ET
    on a US business day. Only then do we set session_label = INTRADAY without relying on the LLM.
    Weekend/holiday publication is never forced to INTRADAY; the LLM decides.
    """
    latest_et = _latest_published_at_et(articles)
    if latest_et is None:
        return False
    if not is_us_business_day(latest_et.date()):
        return False
    # 9:00 AM ET ≤ time < 4:00 PM ET (16:00) → intraday
    return 9 <= latest_et.hour < 16


def _parse_story_json(raw: str) -> Optional[Dict[str, Any]]:
    """
    Parse JSON from LLM, with repair for truncated or slightly malformed output.
    Returns dict or None.
    """
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Log a snippet for debugging (around error position if available)
        pos = getattr(e, "pos", None)
        if pos is not None and 0 <= pos < len(raw):
            start = max(0, pos - 200)
            end = min(len(raw), pos + 200)
            snippet = raw[start:end].replace("\n", " ")
            logger.debug("Story LLM raw snippet near error (pos %s): ...%s...", pos, snippet[:400])
        # Try repair: truncate at last complete ",\n\"" (start of next key) and close object
        repaired = raw.strip()
        # If truncated mid-string or mid-value, find last valid key boundary and close
        last_brace = repaired.rfind("}")
        if last_brace > 0:
            # Try parsing up to and including last complete }
            candidate = repaired[: last_brace + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        # Close unclosed braces/brackets
        open_braces = repaired.count("{") - repaired.count("}")
        open_brackets = repaired.count("[") - repaired.count("]")
        if open_braces > 0 or open_brackets > 0:
            suffix = ""
            if repaired.rstrip().endswith('"'):
                suffix = '"'
            suffix += "]" * open_brackets + "}" * open_braces
            try:
                return json.loads(repaired + suffix)
            except json.JSONDecodeError:
                pass
        logger.warning("Story LLM JSON parse error: %s", e)
        return None


async def story_llm_call(
    client: AsyncOpenAI,
    model: str,
    anchor_title: Optional[str],
    anchor_summary: Optional[str],
    articles: List[Dict],
    asof_date: date,
    ticker: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    One LLM call for one story cluster. Returns parsed story dict for DB or None on failure/omit.
    When articles are unrelated to the given ticker, the LLM may return omit_story: true; then we return None.
    """
    prompt = _build_cluster_prompt(ticker, anchor_title, anchor_summary, articles, asof_date)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        raw = (resp.choices[0].message.content or "").strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)
        data = _parse_story_json(raw)
        if data is None:
            return None
        if data.get("omit_story") is True:
            return None
        result = _normalize_story_dict(data)
        # Rule: if latest published_at (UTC) in ET is 9:00am–4:00pm on a US business day → INTRADAY (no LLM needed)
        if _is_intraday_by_time(articles):
            result["session_label"] = "INTRADAY"
            result["session_confidence"] = 1.0
        return result
    except json.JSONDecodeError as e:
        logger.warning("Story LLM JSON parse error: %s", e)
        return None
    except Exception as e:
        logger.warning("Story LLM call failed: %s", e)
        return None


def _normalize_story_dict(data: Dict) -> Dict[str, Any]:
    """Ensure keys and types match story table."""
    out = {}
    out["title"] = (data.get("title") or "").strip()
    out["summary"] = (data.get("summary") or "").strip()
    out["topics"] = data.get("topics")
    if not isinstance(out["topics"], list):
        out["topics"] = []
    out["session_label"] = (data.get("session_label") or "UNKNOWN").strip().upper()
    if out["session_label"] not in ("OVERNIGHT", "INTRADAY", "MIXED", "UNKNOWN"):
        out["session_label"] = "UNKNOWN"
    out["session_confidence"] = float(data.get("session_confidence") or 0)
    out["event_time_evidence"] = data.get("event_time_evidence")
    if not isinstance(out["event_time_evidence"], list):
        out["event_time_evidence"] = []
    out["risk_horizon"] = (data.get("risk_horizon") or "").strip() or None
    out["prob_move_ge_1pct"] = _float_or_none(data.get("prob_move_ge_1pct"))
    out["prob_move_ge_2pct"] = _float_or_none(data.get("prob_move_ge_2pct"))
    out["expected_abs_move_pct"] = _float_or_none(data.get("expected_abs_move_pct"))
    out["direction_bias"] = (data.get("direction_bias") or "NEUTRAL").strip().upper()
    if out["direction_bias"] not in ("UP", "DOWN", "NEUTRAL", "MIXED"):
        out["direction_bias"] = "NEUTRAL"
    out["risk_confidence"] = float(data.get("risk_confidence") or 0)
    out["risk_drivers"] = data.get("risk_drivers") if isinstance(data.get("risk_drivers"), list) else []
    out["risk_caveats"] = data.get("risk_caveats") if isinstance(data.get("risk_caveats"), list) else []
    out["is_filing_related"] = bool(data.get("is_filing_related"))
    out["filing_form_types"] = data.get("filing_form_types") if isinstance(data.get("filing_form_types"), list) else []
    out["estimated_filing_date_et"] = _date_str_or_none(data.get("estimated_filing_date_et"))
    out["filing_signals"] = data.get("filing_signals") if isinstance(data.get("filing_signals"), list) else []
    return out


def _float_or_none(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _date_str_or_none(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()[:10]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s
    return None
