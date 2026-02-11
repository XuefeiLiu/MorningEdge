"""
Build a single bullet-point "article" from a full macro brief dict (text + JSON columns).
Used to present briefs coherently in the UI.
"""
import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Strip markdown links [text](url) from summary bullets so URLs are not duplicated (Sources section has them).
_LINK_PATTERN = re.compile(r"\s*\[([^\]]*)\]\([^)]*\)\s*")

# Clean related-article display text: no "...", no "[]" (keep content inside brackets).
_DOTS_PATTERN = re.compile(r"\.\.\.|…")
_BRACKETS_PATTERN = re.compile(r"\[([^\]]*)\]")


def _clean_link_display(text: str) -> str:
    """Remove .../… and strip square brackets (keep inner text)."""
    if not text or not isinstance(text, str):
        return (text or "").strip()
    s = _DOTS_PATTERN.sub(" ", text).strip()
    s = _BRACKETS_PATTERN.sub(r"\1", s).strip()
    return " ".join(s.split())

# Text columns to include as labeled bullets (order preserved). Skip: id, as_of_date, created_at, topic, title, summary, summary_bullets, sources, coverage_gap.
TEXT_KEYS_BY_PRIORITY: List[str] = [
    "regime",
    "relative_value_logic",
    "trade_relevance",
    "transmission_by_bloc",
    "scenario_framework",
    "shock_classification",
    "reaction_function",
    "cross_market_consistency",
    "trade_risk_framing",
    "curve_decomposition",
    "macro_credit_transmission",
    "spread_decomposition",
    "segmentation",
    "cross_asset_validation",
    "portfolio_implications",
    "physical_balance",
    "macro_overlay",
    "price_vs_fundamentals",
    "scenario_risk",
    "impact_decomposition",
    "index_vs_factor",
    "macro_consistency",
    "positioning_flows",
    "actionable_framing",
    "mechanism",
    "transmission",
]


def _flatten_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (list, tuple)):
        parts = []
        for i, item in enumerate(v):
            if isinstance(item, dict):
                # e.g. source with title/url
                if "title" in item:
                    parts.append(item.get("title") or item.get("url", ""))
                else:
                    parts.append(json.dumps(item))
            else:
                parts.append(str(item))
        return " • ".join(parts) if parts else ""
    if isinstance(v, dict):
        return json.dumps(v)
    return str(v).strip()


# Magic prefix for multi-column table rows (tab-separated: __TBL__ then column names)
_TBL_PREFIX = "  __TBL__\t"


def _value_to_bullets(label: str, val: Any) -> List[str]:
    """
    Turn a single field value into a list of bullet strings.
    Dicts: if values are dicts (nested), emit table with inner keys as columns; else "  key: value" lines.
    Lists become "Label:" + "  - item".
    """
    if val is None:
        return []
    if isinstance(val, dict):
        # Check if this is a nested dict (values are dicts) -> emit table with columns
        first_val = next(iter(val.values()), None) if val else None
        if first_val is not None and isinstance(first_val, dict):
            inner_keys_set: Dict[str, None] = {}
            for v in val.values():
                if isinstance(v, dict):
                    for k in v:
                        inner_keys_set[k] = None
            inner_keys = list(inner_keys_set)
            if inner_keys:
                lines = [f"{label}:"]
                lines.append(_TBL_PREFIX + "Key\t" + "\t".join(inner_keys))
                for row_key, inner in val.items():
                    if isinstance(inner, dict):
                        cells = [str(inner.get(k, "")).strip() for k in inner_keys]
                    else:
                        cells = [_flatten_value(inner).strip()] + [""] * (len(inner_keys) - 1)
                    lines.append("  " + str(row_key) + "\t" + "\t".join(cells))
                return lines
        # Flat dict: "  key: value" lines
        lines = [f"{label}:"]
        for k, v in val.items():
            vstr = _flatten_value(v).strip()
            if vstr:
                lines.append(f"  {k}: {vstr}")
        return lines if len(lines) > 1 else []  # skip if dict was empty
    if isinstance(val, (list, tuple)) and len(val) > 0:
        # List of items: header + one bullet per item
        lines = [f"{label}:"]
        for item in val:
            s = _flatten_value(item).strip()
            if s:
                lines.append(f"  - {s}")
        return lines if len(lines) > 1 else []
    s = _flatten_value(val).strip()
    if not s:
        return []
    return [f"{label}: {s}"]


def _strip_source_links(text: str) -> str:
    """Remove [Source](url) or [text](url) from bullet text."""
    return _LINK_PATTERN.sub(" ", text).strip()


def _clean_bullet_text(text: str) -> str:
    """Clean bullet for display: no ..., no [] (keep content inside brackets)."""
    if not text or not isinstance(text, str):
        return (text or "").strip()
    s = _strip_source_links(text)
    s = _DOTS_PATTERN.sub(" ", s).strip()
    s = _BRACKETS_PATTERN.sub(r"\1", s).strip()
    return " ".join(s.split())


def _parse_json_value(val: Any) -> Any:
    """If val is a JSON string (dict or list), parse it so dict-like objects can be rendered as tables."""
    if val is None:
        return val
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return val


def build_article_bullets(brief: Dict[str, Any]) -> List[str]:
    """
    Build an ordered list of bullet/paragraph strings from a full brief dict.
    Order: summary (intro), labeled text fields, summary_bullets, sources. URLs stripped from summary bullets.
    """
    out: List[str] = []

    summary = brief.get("summary")
    if summary and isinstance(summary, str) and summary.strip():
        out.append(summary.strip())

    for key in TEXT_KEYS_BY_PRIORITY:
        val = brief.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        val = _parse_json_value(val)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        label = key.replace("_", " ").title()
        for line in _value_to_bullets(label, val):
            out.append(line)

    bullets = brief.get("summary_bullets")
    if bullets is not None and isinstance(bullets, str):
        try:
            bullets = json.loads(bullets)
        except (json.JSONDecodeError, TypeError):
            bullets = None
    sources = brief.get("sources")
    if sources is not None and not isinstance(sources, list):
        sources = None
    if sources is not None and len(sources) == 0:
        sources = None

    # When both summary_bullets and sources exist: one combined section (bullet text + url per row). No separate sources section.
    if bullets is not None and isinstance(bullets, list) and sources is not None and len(sources) > 0:
        out.append("Related source:")
        cap = 20
        n = min(cap, max(len(bullets), len(sources)))
        for i in range(n):
            text = ""
            url = ""
            if i < len(bullets) and bullets[i] is not None:
                text = _clean_bullet_text(str(bullets[i]).strip())
                if text in ("...", "…"):
                    text = ""
            if i < len(sources):
                if isinstance(sources[i], dict):
                    url = (sources[i].get("url") or "").strip()
                    if not text:
                        raw = (
                            sources[i].get("bullet_summary")
                            or sources[i].get("summary")
                            or sources[i].get("source")
                            or sources[i].get("title")
                            or sources[i].get("url")
                            or ""
                        )
                        text = _clean_link_display((raw if isinstance(raw, str) else str(raw)).strip() or url or "Source")
                else:
                    if not text:
                        text = str(sources[i]).strip()
            if text or url:
                out.append(f"  __BULLET_LINK__\t{text or 'Source'}\t{url}")
        if len(sources) > cap or len(bullets) > cap:
            extra = max(0, max(len(sources), len(bullets)) - cap)
            out.append(f"  __BULLET_LINK__\t… and {extra} more\t")
        return out

    # Only summary_bullets: emit as plain lines (no combined section).
    if bullets is not None and isinstance(bullets, list):
        for b in bullets:
            if b is None:
                continue
            s = _clean_bullet_text(str(b).strip())
            if not s or s.strip() in ("...", "…"):
                continue
            out.append(s)

    # Only sources (or sources without summary_bullets): emit Related news articles.
    if sources is not None and len(sources) > 0:
        out.append("Related news articles:")
        for s in sources[:20]:
            if isinstance(s, dict):
                raw = (
                    s.get("bullet_summary")
                    or s.get("summary")
                    or s.get("source")
                    or s.get("title")
                    or s.get("url")
                    or ""
                )
                raw = (raw if isinstance(raw, str) else str(raw)).strip()
                url = (s.get("url") or "").strip()
            else:
                raw = str(s).strip()
                url = ""
            if raw or url:
                display = _clean_link_display(raw or url or "Source")
                out.append(f"  __LINK__\t{display}\t{url}")
        if len(sources) > 20:
            out.append(f"  __LINK__\t… and {len(sources) - 20} more\t")

    return out
