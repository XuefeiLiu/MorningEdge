"""
Merge into or create a long story from an overnight story.

When a story passes the deserves_long_story gate, this module finds a similar
long story by embedding and either merges the articles into it or creates a new
long story from a long-window RAG + rerank selection.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
from supabase import Client

from backend.config import LONG_STORY_DAYS, RAG_TOP_K_CANDIDATES
from backend.services.embedding_service import get_embedding_service
from backend.pipeline.long_story_service import (
    find_similar_long_story,
    add_article_to_long_story,
    create_long_story,
    refresh_long_story_content,
)
from backend.pipeline.rag_retrieval import retrieve_similar_news
from backend.pipeline.rerank import rerank, rerank_top_n_history, select_top_sorted_by_date

logger = logging.getLogger(__name__)


def _all_articles_same_week(articles: List[Dict[str, Any]]) -> bool:
    """Return True if all articles have published_at in the same ISO week (or no valid dates)."""
    weeks = set()
    for a in articles:
        pub = a.get("published_at")
        if pub is None:
            continue
        try:
            dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00")) if isinstance(pub, str) else pub
            if hasattr(dt, "tzinfo") and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            y, w, _ = dt.isocalendar()
            weeks.add((y, w))
        except (TypeError, ValueError, AttributeError):
            continue
    return len(weeks) <= 1


def _article_text(art: Dict[str, Any]) -> str:
    """Build query text from article title and summary."""
    return ((art.get("title") or "") + " " + (art.get("summary") or "")).strip() or (art.get("title") or "")


async def maybe_merge_or_create_long_story(
    supabase: Client,
    ticker: str,
    articles: List[Tuple[int, Dict[str, Any]]],
    tickers_to_query: Optional[List[str]] = None,
    llm_client: Optional[AsyncOpenAI] = None,
    llm_model: Optional[str] = None,
    story_id: Optional[int] = None,
    story_embedding: Optional[List[float]] = None,
    delta: Optional[Dict[str, int]] = None,
) -> Optional[int]:
    """
    Merge into or create a long story. Callers pass articles as a list of (article_id, article).

    Requires story_id + story_embedding. If a similar long story exists, add all articles to it
    and refresh once. If no similar long story, create a new one using RAG + rerank + LLM.

    Returns long_story_id when we merged into an existing long story; None otherwise.
    """
    if not articles:
        logger.warning("maybe_merge_or_create_long_story requires non-empty articles")
        return None
    if delta is None:
        delta = {}
    if story_id is None or story_embedding is None:
        logger.warning("story_id and story_embedding are required; skipping")
        return None

    emb_svc = get_embedding_service()
    embedding = story_embedding
    ticker_upper = ticker.strip().upper()

    similar = await find_similar_long_story(supabase, ticker, embedding)

    if similar:
        long_story_id = similar["id"]
        any_added = False
        seen_merge_ids: set = set()
        for aid, art in articles:
            if aid in seen_merge_ids:
                continue
            seen_merge_ids.add(aid)
            art_ticker = (art.get("ticker") or ticker)
            art_ticker = art_ticker.strip().upper() if isinstance(art_ticker, str) else ticker_upper
            if await add_article_to_long_story(supabase, long_story_id, ticker_upper, aid, art_ticker):
                any_added = True
        if any_added:
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                supabase.table("long_stories").update({"last_updated_at": now_iso}).eq("id", long_story_id).execute()
            except Exception as upd_e:
                logger.debug("Could not update long_story last_updated_at: %s", upd_e)
            if llm_client and llm_model:
                try:
                    await refresh_long_story_content(supabase, long_story_id, llm_client, llm_model)
                except Exception as ref_e:
                    logger.debug("Could not refresh long_story content: %s", ref_e)
            delta["storylines_updated"] = delta.get("storylines_updated", 0) + 1
            logger.info("Merged %d articles into long_story %s for ticker %s", len(articles), long_story_id, ticker)
            return int(long_story_id)
        return None


    story_article_ids = {aid for aid, _ in articles}
    story_article_dicts = [art for _, art in articles]
    now = datetime.now(timezone.utc)
    long_end = now
    long_start = now - timedelta(days=LONG_STORY_DAYS)
    similar_long = await retrieve_similar_news(
        supabase,
        tickers_to_query or [ticker_upper],
        embedding,
        exclude_article_ids=story_article_ids,
        limit=RAG_TOP_K_CANDIDATES,
        start_date=long_start,
        end_date=long_end,
    )
    similar_long = [a for a in (similar_long or []) if a.get("id") not in story_article_ids]
    story_query_text = " ".join(_article_text(art) for _, art in articles)
    reranked_long = rerank(story_query_text, similar_long, RAG_TOP_K_CANDIDATES) if similar_long else []
    top_n_long = rerank_top_n_history()
    selected_long = select_top_sorted_by_date(reranked_long, max_articles=top_n_long)
    if not selected_long:
        logger.debug("No long-window articles for story (article_ids=%s), skipping long story", story_article_ids)
        return None
    if _all_articles_same_week(selected_long):
        logger.debug(
            "All %d selected long-story articles from same week; skipping long story for story (article_ids=%s)",
            len(selected_long),
            story_article_ids,
        )
        return None
    # Deduplicate: story articles first, then selected_long, keyed by article id
    seen_hist_ids: set = set()
    historical_articles = []
    for art in story_article_dicts + selected_long:
        aid = art.get("id")
        if aid is not None and aid not in seen_hist_ids:
            historical_articles.append(art)
            seen_hist_ids.add(aid)
    try:
        long_result = await create_long_story(
            supabase, ticker, historical_articles, llm_client, model=llm_model
        )
        long_story_id = long_result[0]
        if long_story_id is not None:
            delta["storylines_created"] = delta.get("storylines_created", 0) + 1
            logger.info("Created long_story %s for ticker %s", long_story_id, ticker)
            try:
                row = (
                    supabase.table("long_stories")
                    .select("title, canonical_theme, summary")
                    .eq("id", long_story_id)
                    .limit(1)
                    .execute()
                )
                rdata = (row.data or [{}])[0]
                text_for_emb = f"{rdata.get('title') or ''}\n{rdata.get('canonical_theme') or ''}\n{rdata.get('summary') or ''}".strip()
                if text_for_emb:
                    emb = await emb_svc.get_embeddings([text_for_emb])
                    if emb is not None and len(emb) > 0:
                        vec = emb[0].tolist() if hasattr(emb[0], "tolist") else list(emb[0])
                        supabase.table("long_stories").update({"embedding": vec}).eq("id", long_story_id).execute()
            except Exception as emb_e:
                logger.warning("Could not set embedding on long_story %s: %s", long_story_id, emb_e)
    except Exception as e:
        logger.warning("Failed to create long story for articles %s: %s", story_article_ids, e)
    return None
