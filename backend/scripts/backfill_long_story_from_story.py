"""
Backfill long_stories from all current story rows.

For each story: pick anchor (or first) linked article, run "deserves long story" LLM gate,
then merge or create long story via maybe_merge_or_create_long_story (story_id path).
Stories without ticker or without a linked article are skipped.

Run after story.embedding is populated (e.g. run backfill_story_embeddings first if needed).

Usage:
  python -m backend.scripts.backfill_long_story_from_story [--limit N] [--concurrency N] [--skip-deserves]
"""
import argparse
import asyncio
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from supabase import Client

from backend.config import OPENAI_API_KEY
from backend.storage.embedding_utils import parse_embedding_from_db
from backend.storage.supabase_client import get_supabase_client
from backend.pipeline.overnight_pipeline.config import OVERNIGHT_LLM_MODEL
from backend.pipeline.overnight_pipeline.long_story_gate import deserves_long_story as deserves_long_story_llm
from backend.pipeline.rag_retrieval import get_related_tickers
from backend.pipeline.maybe_merge_or_create_long_story import maybe_merge_or_create_long_story

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.ERROR)


def _pick_anchor_article_id(links: List[Dict], id_to_article: Dict[int, Dict]) -> Optional[int]:
    """Pick best article for a story: ANCHOR role first, else use_anchor, else first linked."""
    if not links:
        return None
    for link in links:
        aid = link.get("article_id")
        if aid is not None and id_to_article.get(aid):
            if link.get("role") == "ANCHOR" or link.get("use_anchor"):
                return int(aid)
    aid = links[0].get("article_id")
    return int(aid) if aid is not None and id_to_article.get(aid) else None


async def run_backfill(
    supabase: Client,
    llm_client: AsyncOpenAI,
    limit: Optional[int] = None,
    concurrency: int = 1,
    skip_deserves: bool = False,
) -> Dict[str, int]:
    """
    Load all stories and their linked articles; for each story run deserves-long-story
    (unless skip_deserves) then merge/create long story. Returns counts.
    """
    # Load all stories
    q = supabase.table("story").select("id, title, summary, topics, embedding, ticker").order("id")
    if limit is not None:
        q = q.limit(limit)
    stories_result = q.execute()
    stories = stories_result.data or []
    if not stories:
        logger.info("No stories to process")
        return {"processed": 0, "skipped_no_ticker": 0, "skipped_no_article": 0, "skipped_not_deserves": 0, "storylines_created": 0, "storylines_updated": 0}

    story_ids = [s["id"] for s in stories]
    # Load all story_article_links for these stories
    all_links: List[Dict] = []
    chunk = 200
    for i in range(0, len(story_ids), chunk):
        part = story_ids[i : i + chunk]
        links_result = supabase.table("story_article_link").select("story_id, article_id, role, use_anchor").in_("story_id", part).execute()
        all_links.extend(links_result.data or [])
    story_to_links: Dict[int, List[Dict]] = defaultdict(list)
    for link in all_links:
        story_to_links[int(link["story_id"])].append(link)
    # Sort each list: ANCHOR first, then use_anchor, then by article_id
    for sid in story_to_links:
        story_to_links[sid].sort(key=lambda x: (0 if x.get("role") == "ANCHOR" or x.get("use_anchor") else 1, x.get("article_id") or 0))

    article_ids = list({int(l["article_id"]) for l in all_links if l.get("article_id") is not None})
    id_to_article: Dict[int, Dict] = {}
    for i in range(0, len(article_ids), chunk):
        part = article_ids[i : i + chunk]
        art_result = supabase.table("news_articles").select("id, ticker, title, summary, published_at").in_("id", part).execute()
        for row in art_result.data or []:
            id_to_article[int(row["id"])] = row

    sem = asyncio.Semaphore(concurrency) if concurrency > 0 else None
    stats = {"processed": 0, "skipped_no_ticker": 0, "skipped_no_article": 0, "skipped_not_deserves": 0, "storylines_created": 0, "storylines_updated": 0}

    async def process_one(story: Dict) -> tuple:
        story_id = story["id"]
        ticker = (story.get("ticker") or "").strip()
        if not ticker:
            return ("no_ticker", 0, 0)
        links = story_to_links.get(story_id, [])
        anchor_aid = _pick_anchor_article_id(links, id_to_article)
        if anchor_aid is None:
            return ("no_article", 0, 0)
        article = id_to_article[anchor_aid]
        if not skip_deserves:
            deserves = await deserves_long_story_llm(
                llm_client,
                OVERNIGHT_LLM_MODEL,
                title=story.get("title") or "",
                summary=story.get("summary") or "",
                topics=story.get("topics"),
            )
            if not deserves:
                return ("not_deserves", 0, 0)
        embedding_list = parse_embedding_from_db(story.get("embedding"))
        task_delta = {"storylines_created": 0, "storylines_updated": 0}
        article_id = int(article.get("id", anchor_aid))
        tickers_to_query = [ticker] + get_related_tickers(ticker, supabase)
        await maybe_merge_or_create_long_story(
            supabase,
            ticker.strip().upper(),
            [(article_id, article)],
            tickers_to_query=tickers_to_query,
            llm_client=llm_client,
            llm_model=OVERNIGHT_LLM_MODEL,
            story_id=story_id,
            story_embedding=embedding_list,
            delta=task_delta,
            story_payload=story,
        )
        return ("ok", task_delta.get("storylines_created", 0), task_delta.get("storylines_updated", 0))

    async def process_with_sem(s: Dict):
        if sem:
            async with sem:
                return await process_one(s)
        return await process_one(s)

    tasks = [process_with_sem(s) for s in stories]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("Story %s failed: %s", stories[i].get("id"), r)
            continue
        reason, created, updated = r
        if reason == "no_ticker":
            stats["skipped_no_ticker"] += 1
        elif reason == "no_article":
            stats["skipped_no_article"] += 1
        elif reason == "not_deserves":
            stats["skipped_not_deserves"] += 1
        else:
            stats["processed"] += 1
            stats["storylines_created"] += created
            stats["storylines_updated"] += updated
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill long_stories from all current story rows.")
    parser.add_argument("--limit", type=int, default=None, help="Max number of stories to process (default: all)")
    parser.add_argument("--concurrency", type=int, default=1, help="Concurrent stories (default: 1)")
    parser.add_argument("--skip-deserves", action="store_true", help="Skip LLM 'deserves long story' gate; process all stories with ticker and article")
    args = parser.parse_args()
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY required")
        return
    supabase = get_supabase_client()
    llm_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    stats = asyncio.run(run_backfill(supabase, llm_client, limit=args.limit, concurrency=args.concurrency, skip_deserves=args.skip_deserves))
    logger.info(
        "Backfill long_story from story done: processed=%s skipped_no_ticker=%s skipped_no_article=%s skipped_not_deserves=%s storylines_created=%s storylines_updated=%s",
        stats["processed"],
        stats["skipped_no_ticker"],
        stats["skipped_no_article"],
        stats["skipped_not_deserves"],
        stats["storylines_created"],
        stats["storylines_updated"],
    )


if __name__ == "__main__":
    main()
