"""
Backfill Elasticsearch RAG indices from Supabase.
Reads news_articles, sec_filing_chunks, macro_kb_chunks, long_stories (with embeddings)
and bulk-indexes into ES. Ensures indices exist first.

Requires ELASTICSEARCH_URL and RAG_USE_ELASTICSEARCH=true for ES to be used.
Usage:
  python -m backend.scripts.backfill_elasticsearch_rag [--batch-size N] [--skip-news] [--skip-filing] [--skip-macro] [--skip-long-stories]
"""
import argparse
import logging
import os
import sys

# Add project root for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.config import RAG_USE_ELASTICSEARCH
from backend.storage.elasticsearch_client import get_elasticsearch_client
from backend.storage.elasticsearch_indices import (
    ensure_indices,
    NEWS_ARTICLES_INDEX,
    SEC_FILING_CHUNKS_INDEX,
    MACRO_KB_CHUNKS_INDEX,
    LONG_STORIES_INDEX,
)
from backend.storage.elasticsearch_sync import (
    bulk_index_news_articles,
    bulk_index_filing_chunks,
    bulk_index_macro_kb_chunks,
    bulk_index_long_stories,
)
from backend.storage.supabase_client import get_supabase_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _count_news_with_embedding(supabase) -> tuple:
    """Return (total_news_articles, count_with_embedding)."""
    try:
        r_all = supabase.table("news_articles").select("id", count="exact").limit(1).execute()
        total = (r_all.count if hasattr(r_all, "count") and r_all.count is not None else 0) or 0
        r_emb = (
            supabase.table("news_articles")
            .select("id", count="exact")
            .not_.is_("embedding", "null")
            .limit(1)
            .execute()
        )
        with_emb = (r_emb.count if hasattr(r_emb, "count") and r_emb.count is not None else 0) or 0
        return (total, with_emb)
    except Exception as e:
        logger.warning("Count news_articles failed: %s", e)
        return (0, 0)


def backfill_news_articles(supabase, client, batch_size: int) -> int:
    total_in_db, with_embedding = _count_news_with_embedding(supabase)
    logger.info(
        "News articles in Supabase: %d total, %d with embedding (only these are indexed)",
        total_in_db, with_embedding,
    )
    if with_embedding == 0:
        logger.warning(
            "No news_articles have embeddings. Run embedding backfill first, or the pipeline will add embeddings for new articles."
        )
        return 0
    total = 0
    offset = 0
    while True:
        try:
            result = (
                supabase.table("news_articles")
                .select("id, ticker, title, summary, url, published_at, source, embedding")
                .not_.is_("embedding", "null")
                .range(offset, offset + batch_size - 1)
                .execute()
            )
        except Exception as e:
            logger.warning("Fetch news_articles failed: %s", e)
            break
        rows = result.data or []
        if not rows:
            break
        n = bulk_index_news_articles(rows)
        total += n
        offset += len(rows)
        logger.info("News articles: indexed %d (total %d)", n, total)
        if len(rows) < batch_size:
            break
    return total


def backfill_filing_chunks(supabase, client, batch_size: int) -> int:
    total = 0
    offset = 0
    while True:
        try:
            result = (
                supabase.table("sec_filing_chunks")
                .select("id, filing_id, ticker, chunk_index, text, section, doc_type, embedding")
                .not_.is_("embedding", "null")
                .range(offset, offset + batch_size - 1)
                .execute()
            )
        except Exception as e:
            logger.warning("Fetch sec_filing_chunks failed: %s", e)
            break
        rows = result.data or []
        if not rows:
            break
        filing_ids = list({r["filing_id"] for r in rows if r.get("filing_id") is not None})
        filing_meta = {}
        if filing_ids:
            try:
                fr = supabase.table("sec_filings").select("id, filed_date, form_type").in_("id", filing_ids).execute()
                for f in (fr.data or []):
                    filing_meta[f["id"]] = {"filed_date": f.get("filed_date"), "form_type": f.get("form_type")}
            except Exception:
                pass
        for r in rows:
            meta = filing_meta.get(r.get("filing_id")) or {}
            r["filed_date"] = meta.get("filed_date")
            r["form_type"] = meta.get("form_type")
        n = bulk_index_filing_chunks(rows)
        total += n
        offset += len(rows)
        logger.info("Filing chunks: indexed %d (total %d)", n, total)
        if len(rows) < batch_size:
            break
    return total


def backfill_macro_kb_chunks(supabase, client, batch_size: int) -> int:
    total = 0
    offset = 0
    while True:
        try:
            result = (
                supabase.table("macro_kb_chunks")
                .select("id, book_id, chunk_index, text, embedding")
                .not_.is_("embedding", "null")
                .range(offset, offset + batch_size - 1)
                .execute()
            )
        except Exception as e:
            logger.warning("Fetch macro_kb_chunks failed: %s", e)
            break
        rows = result.data or []
        if not rows:
            break
        n = bulk_index_macro_kb_chunks(rows)
        total += n
        offset += len(rows)
        logger.info("Macro KB chunks: indexed %d (total %d)", n, total)
        if len(rows) < batch_size:
            break
    return total


def backfill_long_stories(supabase, client, batch_size: int) -> int:
    total = 0
    offset = 0
    while True:
        try:
            result = (
                supabase.table("long_stories")
                .select("id, ticker, title, canonical_theme, summary, embedding")
                .not_.is_("embedding", "null")
                .range(offset, offset + batch_size - 1)
                .execute()
            )
        except Exception as e:
            logger.warning("Fetch long_stories failed: %s", e)
            break
        rows = result.data or []
        if not rows:
            break
        n = bulk_index_long_stories(rows)
        total += n
        offset += len(rows)
        logger.info("Long stories: indexed %d (total %d)", n, total)
        if len(rows) < batch_size:
            break
    return total


def main():
    parser = argparse.ArgumentParser(description="Backfill Elasticsearch RAG indices from Supabase")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size per table")
    parser.add_argument("--skip-news", action="store_true", help="Skip news_articles")
    parser.add_argument("--skip-filing", action="store_true", help="Skip sec_filing_chunks")
    parser.add_argument("--skip-macro", action="store_true", help="Skip macro_kb_chunks")
    parser.add_argument("--skip-long-stories", action="store_true", help="Skip long_stories")
    args = parser.parse_args()

    if not RAG_USE_ELASTICSEARCH:
        logger.warning("RAG_USE_ELASTICSEARCH is not enabled or ELASTICSEARCH_URL is unset. Exiting.")
        return

    client = get_elasticsearch_client()
    if client is None:
        logger.error("Elasticsearch client unavailable. Check ELASTICSEARCH_URL and connectivity.")
        return

    ensure_indices(client)
    supabase = get_supabase_client()

    total_news = 0
    total_filing = 0
    total_macro = 0
    total_long = 0

    if not args.skip_news:
        total_news = backfill_news_articles(supabase, client, args.batch_size)
    if not args.skip_filing:
        total_filing = backfill_filing_chunks(supabase, client, args.batch_size)
    if not args.skip_macro:
        total_macro = backfill_macro_kb_chunks(supabase, client, args.batch_size)
    if not args.skip_long_stories:
        total_long = backfill_long_stories(supabase, client, args.batch_size)

    logger.info(
        "Backfill complete: news_articles=%d sec_filing_chunks=%d macro_kb_chunks=%d long_stories=%d",
        total_news, total_filing, total_macro, total_long,
    )
    # Verify: report ES index doc counts
    try:
        for name, idx in [
            ("news_articles", NEWS_ARTICLES_INDEX),
            ("sec_filing_chunks", SEC_FILING_CHUNKS_INDEX),
            ("macro_kb_chunks", MACRO_KB_CHUNKS_INDEX),
            ("long_stories", LONG_STORIES_INDEX),
        ]:
            c = client.count(index=idx)
            logger.info("ES index %s: %d docs", name, c.get("count", 0))
    except Exception as e:
        logger.warning("ES index count check failed: %s", e)


if __name__ == "__main__":
    main()
