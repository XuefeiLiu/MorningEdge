"""
Insert into story_article_link, story_filing_link.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from supabase import Client

logger = logging.getLogger(__name__)


def insert_story_article_links(
    supabase: Client,
    story_id: str,
    article_roles: List[dict],
) -> int:
    """
    article_roles: list of { "article_id": int, "role": "PRIMARY"|"SUPPORTING"|"ANCHOR", "score": float?, "use_anchor": bool? }
    Returns count inserted.
    """
    if not story_id or not article_roles:
        return 0
    rows = []
    for r in article_roles:
        aid = r.get("article_id")
        if aid is None:
            continue
        role = (r.get("role") or "SUPPORTING").strip().upper()
        if role not in ("PRIMARY", "SUPPORTING", "ANCHOR"):
            role = "SUPPORTING"
        rows.append({
            "story_id": story_id,
            "article_id": int(aid),
            "role": role,
            "use_anchor": bool(r.get("use_anchor", False)),
            "score": r.get("score"),
        })
    if not rows:
        return 0
    try:
        supabase.table("story_article_link").insert(rows).execute()
        return len(rows)
    except Exception as e:
        logger.warning("insert_story_article_links failed: %s", e)
        return 0


def insert_story_filing_link(
    supabase: Client,
    story_id: str,
    filing_id: int,
    link_type: str = "MOST_RECENT",
    score: Optional[float] = None,
    top_chunk_id: Optional[int] = None,
) -> bool:
    """One story -> one filing, optionally pointing at the top evidence chunk. Returns True if inserted."""
    if not story_id or filing_id is None:
        return False
    row = {
        "story_id": story_id,
        "filing_id": int(filing_id),
        "link_type": link_type,
        "score": score,
    }
    if top_chunk_id is not None:
        row["top_chunk_id"] = int(top_chunk_id)
    try:
        supabase.table("story_filing_link").insert(row).execute()
        return True
    except Exception as e:
        logger.warning("insert_story_filing_link failed: %s", e)
        return False
