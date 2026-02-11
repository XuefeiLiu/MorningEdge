"""
Deterministic string IDs for macro digest tables.
Application supplies id (bigint) on insert; use these helpers + _string_id_to_bigint.
Same hashing as news_articles_save / macro_articles_save / filing_store.
"""
from hashlib import md5
from datetime import date
from typing import Optional


def _string_id_to_bigint(string_id: str) -> int:
    """Convert string ID to bigint (MD5, first 7 bytes, mod max_bigint)."""
    hash_bytes = md5(string_id.encode("utf-8")).digest()
    bigint_id = int.from_bytes(hash_bytes[:7], byteorder="big", signed=False)
    return bigint_id % 9223372036854775807


def macro_raw_string_id(url: str, published_at_iso: str) -> str:
    """Stable string ID for macro_raw_items row."""
    raw = f"{url or ''}{published_at_iso or ''}"
    h = md5(raw.encode("utf-8")).hexdigest()[:12]
    return f"macro_raw_{h}"


def macro_brief_string_id(as_of_date: date, topic: str) -> str:
    """Stable string ID for macro_daily_briefs row. topic should be slug (e.g. FX, Fiscal_Policy)."""
    d = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    t = (topic or "").replace(" ", "_").strip() or "unknown"
    return f"macro_brief_{d}_{t}"


def macro_brief_asset_string_id(table_key: str, as_of_date: date) -> str:
    """Stable string ID for per-asset brief table (fx, rates, credit, commodity, equity). One row per date."""
    d = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    return f"macro_brief_{table_key}_{d}"


def macro_brief_policy_string_id(as_of_date: date, topic: str) -> str:
    """Stable string ID for macro_brief_policy row. topic: Fiscal Policy | Monetary Policy | Trump."""
    d = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    t = (topic or "").replace(" ", "_").strip() or "unknown"
    return f"macro_brief_policy_{d}_{t}"


def macro_book_string_id(source_uri: str) -> str:
    """Stable string ID for macro_kb_books row."""
    h = md5((source_uri or "").encode("utf-8")).hexdigest()[:12]
    return f"macro_book_{h}"


def macro_chunk_string_id(book_string_id: str, chunk_index: int) -> str:
    """Stable string ID for macro_kb_chunks row."""
    return f"macro_chunk_{book_string_id}_{chunk_index}"


def macro_impact_string_id(as_of_date: date, portfolio_id: Optional[str] = None) -> str:
    """Stable string ID for macro_daily_impact_reports row."""
    d = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    pid = (portfolio_id or "default").strip() or "default"
    return f"macro_impact_{d}_{pid}"


def macro_daily_summary_string_id(as_of_date: date) -> str:
    """Stable string ID for macro_daily_summary row (one per date)."""
    d = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)[:10]
    return f"macro_daily_summary_{d}"
