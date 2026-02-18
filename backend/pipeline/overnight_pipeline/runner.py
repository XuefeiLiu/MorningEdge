"""
Overnight pipeline runner: run store/embed data first (Task1-style), then anchors, cluster, LLM per cluster, filing link, persist.
"""
import argparse
import asyncio
import logging
import subprocess
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from openai import AsyncOpenAI
from supabase import Client

from backend.storage.supabase_client import get_supabase_client
from backend.storage.embedding_utils import parse_embedding_from_db
from backend.storage.news_articles_query import get_articles_by_created_time, get_articles_by_published_time
from backend.storage.stocks_query import get_all_stocks
from backend.services.embedding_service import get_embedding_service
from backend.config import OPENAI_API_KEY, GEMINI_GENERATED_SOURCE

from backend.pipeline.store_embed_data import run_store_embed_data
from backend.pipeline.overnight_pipeline.anchors import _is_gemini_article
from backend.pipeline.overnight_pipeline.clustering import run_clustering
from backend.pipeline.overnight_pipeline.story_llm import story_llm_call
from backend.pipeline.overnight_pipeline.filing_link import get_most_recent_filing, get_top_chunks_for_filing
from backend.pipeline.overnight_pipeline.story_store import insert_story
from backend.pipeline.overnight_pipeline.link_store import (
    insert_story_article_links,
    insert_story_filing_link,
)
from backend.pipeline.overnight_pipeline.config import OVERNIGHT_LLM_MODEL, PROMPT_VERSION, FILING_CHUNK_TOP_K
from backend.pipeline.overnight_pipeline.long_story_gate import deserves_long_story as deserves_long_story_llm
from backend.pipeline.rag_retrieval import get_related_tickers
from backend.pipeline.maybe_merge_or_create_long_story import maybe_merge_or_create_long_story

logger = logging.getLogger(__name__)


def _embedding_from_row(row: dict) -> Optional[List[float]]:
    """Use shared parser so Supabase pgvector returned as string is handled."""
    return parse_embedding_from_db(row.get("embedding"))


async def _get_or_embed(
    rows: List[dict],
    text_fn,
    emb_svc,
) -> tuple:
    """Returns (ids, embeddings array). Embeds rows that lack embedding."""
    ids = []
    texts = []
    need_embed_idx = []
    for i, row in enumerate(rows):
        aid = row.get("id")
        if aid is None:
            continue
        ids.append(int(aid))
        emb = _embedding_from_row(row)
        if emb is not None:
            need_embed_idx.append((i, len(ids) - 1, emb))
        else:
            texts.append((len(ids) - 1, text_fn(row)))
    if not ids:
        return [], np.zeros((0, 1536), dtype=np.float32)
    # Build embedding array: use existing or placeholder
    dim = 1536
    if need_embed_idx:
        dim = len(need_embed_idx[0][2])
    embeddings = np.zeros((len(ids), dim), dtype=np.float32)
    for i, j, emb in need_embed_idx:
        embeddings[j] = np.array(emb, dtype=np.float32)
    to_embed = [t[1] for t in texts]
    if to_embed:
        text_list = [t for _, t in texts]
        got = await emb_svc.get_embeddings(text_list)
        if got is not None and len(got) == len(text_list):
            for (idx, _), vec in zip(texts, got):
                embeddings[idx] = vec if hasattr(vec, "tolist") else list(vec)
    return ids, embeddings


async def run_overnight_pipeline(
    asof_date: Optional[date] = None,
    tickers: Optional[List[str]] = None,
    supabase: Optional[Client] = None,
    llm_client: Optional[AsyncOpenAI] = None,
    pipeline_version: Optional[str] = None,
    skip_store_embed: bool = False,
    run_long_story: bool = True,
) -> Dict[str, Any]:
    """
    Run the overnight story pipeline for the given date.
    Runs store/embed data first (Task1-style collect+store with embeddings, including Gemini for anchors),
    then anchors, cluster, LLM per cluster, filing link, persist.
    Returns stats: store_embed_*, stories_created, links_created, filing_links, chunk_links, errors.
    """
    if asof_date is None:
        asof_date = datetime.now(timezone.utc).date()
    if supabase is None:
        supabase = get_supabase_client()
    if pipeline_version is None:
        try:
            pipeline_version = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
                cwd="/",
            ).strip()
        except Exception:
            pipeline_version = "unknown"

    # Step 1: Store/embed data (Task1-style) so news_articles is populated, including Gemini for anchors
    store_embed_stats: Dict[str, Any] = {}
    if not skip_store_embed:
        logger.info("Overnight pipeline: running store/embed data first...")
        store_embed_tickers = tickers
        if store_embed_tickers is None:
            stocks = get_all_stocks(supabase)
            store_embed_tickers = [(s.get("ticker") or "").strip() for s in stocks if (s.get("ticker") or "").strip()]
        store_embed_stats = await run_store_embed_data(
            supabase,
            tickers=store_embed_tickers,
            include_gemini=True,
            include_alpha_vantage=True,
            include_massive=True,
            run_macro=True,
            run_macro_digest=None,
            run_filing_update=None,
            valid_tickers=None,
        )
        logger.info(
            "Store/embed done: articles_stored=%s",
            store_embed_stats.get("articles_stored", 0),
        )

    end = datetime.now(timezone.utc)
    # Gemini-source articles: filter by created_at (ingestion time), same 3h window
    created_start = end - timedelta(hours=3)
    gemini_articles = [a for a in get_articles_by_created_time(supabase, start_time=created_start, end_time=end, limit=5000) if _is_gemini_article(a)]
    # Other sources: filter by published_at from now-18h to now
    published_start = end - timedelta(hours=18)
    other_articles = [a for a in get_articles_by_published_time(supabase, start_time=published_start, end_time=end, limit=5000) if not _is_gemini_article(a)]
    all_articles = gemini_articles + other_articles
    if tickers:
        ts = {t.strip().upper() for t in tickers}
        all_articles = [a for a in all_articles if (a.get("ticker") or "").strip().upper() in ts]
    if not all_articles:
        logger.info("No articles for asof_date=%s", asof_date)
        return {
            **store_embed_stats,
            "stories_created": 0,
            "links_created": 0,
            "filing_links": 0,
            "chunk_links": 0,
        }

    anchor_seeds = [a for a in all_articles if _is_gemini_article(a)]
    non_anchor_articles = [a for a in all_articles if a.get("id") not in {s["id"] for s in anchor_seeds}]
    # Anchor seeds as list of dict with article_id for get_anchor_seeds shape - we already have full rows
    anchor_rows = anchor_seeds
    anchor_article_ids = [int(a["id"]) for a in anchor_rows]
    emb_svc = get_embedding_service()

    def article_text(row):
        return ((row.get("title") or "") + " " + (row.get("summary") or "")).strip() or " "

    anchor_ids, anchor_embeddings = await _get_or_embed(anchor_rows, article_text, emb_svc)
    non_anchor_ids, non_anchor_embeddings = await _get_or_embed(non_anchor_articles, article_text, emb_svc)
    id_to_article = {int(a["id"]): a for a in all_articles}

    clusters = run_clustering(
        anchor_article_ids=anchor_article_ids,
        anchor_embeddings=anchor_embeddings,
        article_ids=non_anchor_ids,
        article_embeddings=non_anchor_embeddings,
    )
    if not clusters:
        logger.info("No clusters for asof_date=%s", asof_date)
        return {
            **store_embed_stats,
            "stories_created": 0,
            "links_created": 0,
            "filing_links": 0,
            "chunk_links": 0,
        }

    if llm_client is None:
        if not OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY required for overnight pipeline LLM")
            return {
                **store_embed_stats,
                "stories_created": 0,
                "links_created": 0,
                "filing_links": 0,
                "chunk_links": 0,
                "errors": ["no_llm"],
            }
        llm_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def call_llm_for_cluster(cluster: dict) -> tuple:
        """Returns (cluster, story_payload or None)."""
        anchor_aid = cluster.get("anchor_article_id")
        article_ids = cluster.get("article_ids") or []
        if not article_ids:
            return (cluster, None)
        articles_for_llm = []
        for aid in article_ids:
            a = id_to_article.get(aid)
            if a:
                articles_for_llm.append({
                    "id": a["id"],
                    "title": a.get("title") or "",
                    "summary": a.get("summary") or "",
                    "source": a.get("source") or "",
                    "published_at": a.get("published_at"),
                })
        if not articles_for_llm:
            return (cluster, None)
        ticker = None
        if article_ids:
            ticker = (id_to_article.get(article_ids[0]) or {}).get("ticker")
        if not ticker and anchor_aid is not None:
            ticker = (id_to_article.get(anchor_aid) or {}).get("ticker")
        ticker = (ticker or "").strip() or None
        anchor_title = None
        anchor_summary = None
        if anchor_aid is not None:
            anc = id_to_article.get(anchor_aid)
            if anc:
                anchor_title = anc.get("title") or ""
                anchor_summary = anc.get("summary") or ""
        story_payload = await story_llm_call(
            llm_client,
            OVERNIGHT_LLM_MODEL,
            anchor_title,
            anchor_summary,
            articles_for_llm,
            asof_date,
            ticker=ticker,
        )
        return (cluster, story_payload)

    llm_results = await asyncio.gather(*[call_llm_for_cluster(c) for c in clusters])

    async def persist_story(cluster: dict, story_payload: dict) -> tuple:
        """Returns (stories_created, links_created, filing_links, story_id, cluster, story_payload, story_embedding, ticker)."""
        anchor_aid = cluster.get("anchor_article_id")
        article_ids = cluster.get("article_ids") or []
        ticker = None
        if article_ids:
            ticker = (id_to_article.get(article_ids[0]) or {}).get("ticker")
        if not ticker and anchor_aid:
            ticker = (id_to_article.get(anchor_aid) or {}).get("ticker")
        ticker = (ticker or "").strip() or None
        seed = "_".join(str(a) for a in sorted(article_ids)) if article_ids else ""
        n_articles = len(article_ids)
        # Build embedding for story (title + topics + summary) for DB and long-story similarity
        title = (story_payload.get("title") or "").strip()
        summary = (story_payload.get("summary") or "").strip()
        topics = story_payload.get("topics") or []
        theme = " ".join(topics) if isinstance(topics, list) else (str(topics) if topics else "")
        story_text = "\n".join(filter(None, [title, theme, summary])) or title or summary
        story_embedding_list: Optional[List[float]] = None
        if story_text:
            emb_result = await emb_svc.get_embeddings([story_text])
            if emb_result is not None and len(emb_result) > 0:
                story_embedding_list = emb_result[0].tolist() if hasattr(emb_result[0], "tolist") else list(emb_result[0])
        story_id = insert_story(
            supabase,
            asof_date,
            story_payload,
            ticker=ticker,
            cluster_type=cluster.get("cluster_type"),
            cluster_size=n_articles,
            pipeline_version=pipeline_version,
            llm_model=OVERNIGHT_LLM_MODEL,
            prompt_version=PROMPT_VERSION,
            seed=seed,
            embedding=story_embedding_list,
        )
        if story_id is None:
            return (0, 0, 0, None, None, None, None, None)
        article_roles = []
        for aid in article_ids:
            role = "ANCHOR" if aid == anchor_aid else "SUPPORTING"
            article_roles.append({"article_id": aid, "role": role, "use_anchor": role == "ANCHOR"})
        n_links = insert_story_article_links(supabase, story_id, article_roles)
        filing_links = 0
        if story_payload.get("is_filing_related") and ticker:
            story_d = story_payload.get("estimated_filing_date_et") or asof_date
            if isinstance(story_d, str):
                try:
                    story_d = datetime.strptime(story_d[:10], "%Y-%m-%d").date()
                except ValueError:
                    story_d = asof_date
            form_types = story_payload.get("filing_form_types") or []
            filing = get_most_recent_filing(
                supabase, ticker, form_types=form_types or None, max_filed_date=story_d
            )
            if filing:
                query_text = (story_payload.get("summary") or "").strip() or (story_payload.get("title") or "")
                top_chunk_id = None
                score = None
                if query_text:
                    q_emb = await emb_svc.get_embeddings([query_text])
                    if q_emb is not None and len(q_emb) > 0:
                        q_vec = q_emb[0].tolist() if hasattr(q_emb[0], "tolist") else list(q_emb[0])
                        top_chunks = await get_top_chunks_for_filing(
                            supabase, filing["id"], q_vec, top_k=1
                        )
                        if top_chunks:
                            top_chunk_id = top_chunks[0].get("chunk_id")
                            score = top_chunks[0].get("score")
                insert_story_filing_link(
                    supabase, story_id, filing["id"], "MOST_RECENT", score, top_chunk_id=top_chunk_id
                )
                filing_links = 1
        return (1, n_links, filing_links, story_id, cluster, story_payload, story_embedding_list, ticker)

    persist_tasks = [persist_story(c, p) for c, p in llm_results if p]
    persist_results = await asyncio.gather(*persist_tasks) if persist_tasks else []
    stories_created = sum(r[0] for r in persist_results)
    links_created = sum(r[1] for r in persist_results)
    filing_links = sum(r[2] for r in persist_results)

    # Long-story flow: parallel per story (deserves-long-story gate then merge/create); optional, default on
    delta = {"storylines_created": 0, "storylines_updated": 0}
    if run_long_story:

        async def process_one_long_story(r: tuple) -> tuple:
            """Returns (storylines_created_delta, storylines_updated_delta) for this story.
            Uses all non-Gemini articles in the cluster for merge/create long story (not just the anchor).
            """
            if r[0] == 0 or r[3] is None:
                return (0, 0)
            _stories_created, _links, _filing_links, story_id, cluster, story_payload, story_embedding_list, ticker = r
            if not ticker:
                return (0, 0)
            article_ids = (cluster or {}).get("article_ids") or []
            # Only use articles that are not Gemini-generated for long story merge/create
            non_gemini_articles = []
            seen_article_ids: set = set()
            for aid in article_ids:
                art = (id_to_article or {}).get(aid)
                if art and not _is_gemini_article(art):
                    art_id = int(art.get("id", aid))
                    if art_id not in seen_article_ids:
                        non_gemini_articles.append((art_id, art))
                        seen_article_ids.add(art_id)
            if not non_gemini_articles:
                return (0, 0)
            deserves = await deserves_long_story_llm(
                llm_client,
                OVERNIGHT_LLM_MODEL,
                title=story_payload.get("title") or "",
                summary=story_payload.get("summary") or "",
                topics=story_payload.get("topics"),
            )
            if not deserves:
                return (0, 0)
            task_delta = {"storylines_created": 0, "storylines_updated": 0}
            ticker_upper = ticker.strip().upper()
            tickers_to_query = [ticker_upper] + get_related_tickers(ticker, supabase)
            await maybe_merge_or_create_long_story(
                supabase,
                ticker_upper,
                non_gemini_articles,
                tickers_to_query=tickers_to_query,
                llm_client=llm_client,
                llm_model=OVERNIGHT_LLM_MODEL,
                story_id=story_id,
                story_embedding=story_embedding_list,
                delta=task_delta,
                story_payload=story_payload,
            )
            return (task_delta.get("storylines_created", 0), task_delta.get("storylines_updated", 0))

        long_story_results = await asyncio.gather(*[process_one_long_story(r) for r in persist_results])
        for created, updated in long_story_results:
            delta["storylines_created"] += created
            delta["storylines_updated"] += updated

    logger.info(
        "Overnight pipeline asof_date=%s: stories=%s links=%s filing_links=%s long_storylines_created=%s long_storylines_updated=%s",
        asof_date, stories_created, links_created, filing_links, delta.get("storylines_created", 0), delta.get("storylines_updated", 0),
    )
    return {
        **store_embed_stats,
        "stories_created": stories_created,
        "links_created": links_created,
        "filing_links": filing_links,
        "long_storylines_created": delta.get("storylines_created", 0),
        "long_storylines_updated": delta.get("storylines_updated", 0),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="Overnight story pipeline (store/embed first, then story clustering)")
    parser.add_argument("--asof-date", type=str, default=None, help="Date YYYY-MM-DD (default: today ET)")
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers (default: all stocks for store/embed)")
    parser.add_argument("--skip-store-embed", action="store_true", help="Skip Task1-style collect+store; assume news_articles already populated")
    parser.add_argument("--skip-long-story", action="store_true", help="Skip long-story flow (merge/create long storylines from overnight stories)")
    args = parser.parse_args()
    asof_date = None
    if args.asof_date:
        try:
            asof_date = datetime.strptime(args.asof_date[:10], "%Y-%m-%d").date()
        except ValueError:
            logger.error("Invalid --asof-date")
            return
    tickers = None
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    asyncio.run(run_overnight_pipeline(
        asof_date=asof_date,
        tickers=tickers,
        skip_store_embed=args.skip_store_embed,
        run_long_story=not args.skip_long_story,
    ))
if __name__ == "__main__":
    main()
