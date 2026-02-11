"""
Remove duplicate long stories and their article links.

Long stories live in the long_stories table; links in long_story_article_links.
Duplicate detection:
- With --use-llm (default): use an LLM to group long stories by similar meaning (same ticker).
  Titles with the same or very similar meaning (paraphrases, same event) are merged; keep smallest id.
- With --exact-only: match only by exact (ticker, title) or (ticker, canonical_theme).

For each duplicate: delete its rows in long_story_article_links, then delete the long_stories row.
Keeps one (smallest id) per group.

Requires OPENAI_API_KEY for --use-llm.

Usage:
  python -m backend.scripts.remove_duplicate_long_storylines [--dry-run]
  python -m backend.scripts.remove_duplicate_long_storylines [--dry-run] --use-llm
  python -m backend.scripts.remove_duplicate_long_storylines [--dry-run] --exact-only
"""
import argparse
import asyncio
import json
import logging
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from supabase import Client

from backend.storage.supabase_client import get_supabase_client

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    return (s or "").strip()


def get_long_stories(supabase: Client) -> List[Dict]:
    """Return all long stories from long_stories table (id, ticker, title, canonical_theme)."""
    result = (
        supabase.table("long_stories")
        .select("id, ticker, title, canonical_theme")
        .order("id", desc=False)
        .execute()
    )
    return result.data or []


def _get_llm_client_and_model():
    """Return (AsyncOpenAI client, model name). OpenAI only."""
    from backend.config import OPENAI_API_KEY, OPENAI_MODEL
    from openai import AsyncOpenAI

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")
    return AsyncOpenAI(api_key=OPENAI_API_KEY), OPENAI_MODEL


async def find_similar_duplicate_groups_llm(
    rows_per_ticker: Dict[str, List[Dict]],
) -> List[Tuple[int, List[int]]]:
    """
    For each ticker with 2+ long storylines, ask LLM to group by similar meaning.
    Returns list of (kept_id, [duplicate_id, ...]) with kept_id = smallest id in each group.
    """
    try:
        client, model = _get_llm_client_and_model()
    except ValueError as e:
        logger.warning("LLM not available: %s. Use --exact-only or set API keys.", e)
        return []

    out: List[Tuple[int, List[int]]] = []
    for ticker, rows in rows_per_ticker.items():
        if len(rows) < 2:
            continue
        # Build list of (id, title) for prompt
        items = []
        for r in rows:
            sid = r.get("id")
            title = _normalize(r.get("title") or "")
            theme = _normalize(r.get("canonical_theme") or "")
            text = title if title else theme
            if sid is not None and text:
                items.append({"id": int(sid), "title": text})
        if len(items) < 2:
            continue

        prompt = f"""You are a deduplication assistant. Given the following long story titles (ticker: {ticker}), identify groups where the titles have the same or very similar meaning (same event, same theme, paraphrases). Return only groups of size >= 2.

Stories (id, title):
{json.dumps(items, ensure_ascii=False)}

Output valid JSON only, no other text. Format: {{"duplicate_groups": [[id1, id2], [id3, id4], ...]}}
Each inner array is a list of integer ids that are duplicates. If no two titles have similar meaning, return {{"duplicate_groups": []}}."""

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You output only valid JSON. No markdown, no explanation."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            content = (response.choices[0].message.content or "").strip()
            # Strip markdown code block if present
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```\s*$", "", content)
            data = json.loads(content)
            groups = data.get("duplicate_groups") or []
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, list) or len(group) < 2:
                    continue
                ids = [int(x) for x in group if isinstance(x, (int, float))]
                if len(ids) < 2:
                    continue
                ids.sort()
                kept_id = ids[0]
                duplicate_ids = ids[1:]
                out.append((kept_id, duplicate_ids))
        except json.JSONDecodeError as e:
            logger.warning("LLM JSON parse error for ticker %s: %s", ticker, e)
        except Exception as e:
            logger.warning("LLM call failed for ticker %s: %s", ticker, e)

    return out


def find_duplicate_groups_exact(long_stories_rows: List[Dict]) -> List[Tuple[int, List[int]]]:
    """
    Group long stories by exact (ticker, normalized title) or (ticker, canonical_theme).
    For each group with more than one, return (kept_id, [duplicate_id, ...]) with kept_id = smallest id.
    """
    key_to_rows: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for r in long_stories_rows:
        ticker = (r.get("ticker") or "").strip().upper()
        title = _normalize(r.get("title") or "")
        theme = _normalize(r.get("canonical_theme") or "")
        text = title if title else theme
        key_to_rows[(ticker, text)].append(r)

    out: List[Tuple[int, List[int]]] = []
    for (_ticker, _text), group in key_to_rows.items():
        if len(group) <= 1:
            continue
        group_sorted = sorted(group, key=lambda x: x.get("id") or 0)
        kept_id = group_sorted[0].get("id")
        duplicate_ids = [r.get("id") for r in group_sorted[1:] if r.get("id") is not None]
        if kept_id is not None and duplicate_ids:
            out.append((kept_id, duplicate_ids))
    return out


def _merge_duplicate_groups(groups: List[Tuple[int, List[int]]]) -> List[Tuple[int, List[int]]]:
    """
    Resolve overlapping groups so each duplicate id maps to one canonical kept id.
    If dup_id appears in multiple groups, follow chain to smallest kept id; then return
    (canonical_kept_id, list of all dup_ids that point to it) per kept id.
    """
    dup_to_kept: Dict[int, int] = {}
    for kept_id, duplicate_ids in groups:
        for d in duplicate_ids:
            existing = dup_to_kept.get(d)
            dup_to_kept[d] = min(kept_id, existing) if existing is not None else kept_id
    # Resolve chains: dup_id -> kept_id; if kept_id is itself a duplicate, follow to final kept
    for dup_id in list(dup_to_kept.keys()):
        c = dup_to_kept[dup_id]
        while c in dup_to_kept:
            c = dup_to_kept[c]
        dup_to_kept[dup_id] = c
    # Group by canonical kept_id
    kept_to_dups: Dict[int, List[int]] = defaultdict(list)
    for dup_id, canonical_kept in dup_to_kept.items():
        kept_to_dups[canonical_kept].append(dup_id)
    return [(k, sorted(v)) for k, v in kept_to_dups.items() if v]


async def run_async(dry_run: bool = False, use_llm: bool = True, exact_only: bool = False) -> None:
    supabase = get_supabase_client()
    long_rows = get_long_stories(supabase)
    if not long_rows:
        logger.info("No long stories found. Nothing to do.")
        return

    if exact_only:
        groups = find_duplicate_groups_exact(long_rows)
        logger.info("Using exact match (ticker + title/theme).")
    elif use_llm:
        rows_per_ticker: Dict[str, List[Dict]] = defaultdict(list)
        for r in long_rows:
            t = (r.get("ticker") or "").strip().upper()
            rows_per_ticker[t].append(r)
        groups = await find_similar_duplicate_groups_llm(dict(rows_per_ticker))
        groups = _merge_duplicate_groups(groups)
        logger.info("Using LLM similarity (same/similar meaning per ticker).")
    else:
        groups = find_duplicate_groups_exact(long_rows)
        logger.info("Using exact match (ticker + title/theme).")

    if not groups:
        logger.info("No duplicate long stories found. Nothing to remove.")
        return

    total_duplicates = sum(len(dup_ids) for _kept, dup_ids in groups)
    logger.info("Found %d duplicate long story(ies) in %d group(s)", total_duplicates, len(groups))
    if dry_run:
        for kept_id, dup_ids in groups:
            logger.info("[DRY RUN] Keep id=%s; would remove duplicate ids: %s", kept_id, dup_ids)
        logger.info("[DRY RUN] Would delete long_story_article_links for duplicates, then delete duplicate long_stories rows.")
        return

    for kept_id, duplicate_ids in groups:
        for dup_id in duplicate_ids:
            # 1. Delete article links for the duplicate long story
            del_links = supabase.table("long_story_article_links").delete().eq("long_story_id", dup_id).execute()
            logger.info("Deleted %d link(s) for long_story_id=%s", len(del_links.data or []), dup_id)

            # 2. Delete the duplicate long story row
            supabase.table("long_stories").delete().eq("id", dup_id).execute()
            logger.info("Deleted duplicate long story id=%s (kept id=%s)", dup_id, kept_id)

    logger.info("Done. Removed %d duplicate long story(ies).", total_duplicates)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove duplicate long stories (long_stories table); use LLM to detect similar meaning (default) or exact ticker+title/theme with --exact-only."
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be done")
    parser.add_argument("--exact-only", action="store_true", help="Skip LLM; match only by exact ticker+title/theme")
    args = parser.parse_args()
    asyncio.run(run_async(dry_run=args.dry_run, use_llm=not args.exact_only, exact_only=args.exact_only))


if __name__ == "__main__":
    main()
