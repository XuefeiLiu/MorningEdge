"""
Re-embed rows using OpenAI text-embedding-3-small (1536-dim) for news_articles, macro_articles, sec_filing_chunks.
Default: only rows where embedding IS NULL (fill gaps). Use --all to re-embed every row (e.g. after migration).

Requires: OPENAI_API_KEY set. Run DB migration (embedding_1536_openai.sql) first so columns are vector(1536).

Usage:
  python -m backend.scripts.backfill_embeddings_new_model [--table TABLE] [--all] [--batch-size N] ...

  --table: news_articles | macro_articles | sec_filing_chunks | all (default: all)
  --all: process all rows (default: only rows where embedding IS NULL)
  --batch-size: rows per batch (default: 200 for articles, 100 for chunks)
  --update-concurrency: parallel DB updates per batch (default: 100)
  --embedding-concurrency: parallel embedding requests per batch (default: 6)
"""
import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from backend.storage.supabase_client import get_supabase_client
from backend.storage.embedding_utils import get_embeddings

DEFAULT_BATCH_SIZE_NEWS = 200
DEFAULT_BATCH_SIZE_CHUNKS = 100
DEFAULT_UPDATE_CONCURRENCY = 100
# Lower defaults to avoid OpenAI TPM rate limit (1M tokens/min); use --embedding-concurrency / --embedding-max-texts to tune
DEFAULT_EMBEDDING_CONCURRENCY = 4
# Max texts per single API request (smaller = fewer tokens per request, less TPM burst)
DEFAULT_EMBEDDING_MAX_TEXTS_PER_REQUEST = 32

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.ERROR)


def is_retryable_error(error: Exception) -> bool:
    error_str = str(error).lower()
    if "520" in error_str or "522" in error_str:
        return True
    return any(
        k in error_str
        for k in ("timeout", "connection", "network", "temporary", "retry", "rate limit", "too many requests")
    )


def _is_statement_timeout(exc: Exception) -> bool:
    """Detect Postgres statement timeout (57014) from postgrest APIError or similar."""
    s = (str(exc) + repr(exc)).lower()
    if "57014" in s or "statement timeout" in s:
        return True
    if exc.args and isinstance(exc.args[0], dict):
        payload = exc.args[0]
        if payload.get("code") == "57014":
            return True
        if "timeout" in str(payload.get("message", "")).lower():
            return True
    code = getattr(exc, "code", None)
    if code == "57014" or code == 57014:
        return True
    return False


async def get_embeddings_parallel(
    texts: List[str],
    concurrency: int,
    max_texts_per_request: int = DEFAULT_EMBEDDING_MAX_TEXTS_PER_REQUEST,
) -> Optional[np.ndarray]:
    """
    Get embeddings with batching: split into chunks of max_texts_per_request,
    then run up to concurrency requests in parallel. Fewer, larger batches = faster.
    """
    if not texts:
        return None
    n = len(texts)
    # Sub-batches of size <= max_texts_per_request (e.g. 64), then run in parallel (up to concurrency)
    sub_batches = [texts[i : i + max_texts_per_request] for i in range(0, n, max_texts_per_request)]
    if len(sub_batches) == 1:
        return await get_embeddings(sub_batches[0])
    tasks = [get_embeddings(sb) for sb in sub_batches]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("Embedding sub-batch %s failed: %s", i, r)
            return None
        if r is None:
            return None
        out.append(r)
    return np.vstack(out)


def _sync_update_row(
    supabase,
    table: str,
    id_column: str,
    row_id: Any,
    embedding: List[float],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> bool:
    """Sync Supabase update (run in thread pool so it doesn't block the event loop)."""
    for attempt in range(max_retries):
        try:
            r = supabase.table(table).update({"embedding": embedding}).eq(id_column, row_id).execute()
            if r.data:
                return True
            return False
        except Exception as e:
            if attempt < max_retries - 1 and is_retryable_error(e):
                time.sleep(base_delay * (2**attempt))
            else:
                logger.debug("Update %s %s=%s failed: %s", table, id_column, row_id, e)
                return False
    return False


async def backfill_table(
    supabase,
    table: str,
    id_column: str,
    text_columns: Tuple[str, ...],
    batch_size: int,
    update_concurrency: int,
    embedding_concurrency: int,
    embedding_max_texts_per_request: int = DEFAULT_EMBEDDING_MAX_TEXTS_PER_REQUEST,
    executor: Optional[ThreadPoolExecutor] = None,
    empty_only: bool = True,
) -> Tuple[int, int, int]:
    """
    Re-embed rows in table. text_columns = (primary, fallback, ...) e.g. ("summary", "title");
    for sec_filing_chunks use ("text",). Returns (processed, updated, failed).
    By default (empty_only=True) only rows where embedding IS NULL are selected. Use empty_only=False to re-embed all rows.
    """
    primary, *fallbacks = text_columns
    processed = updated = failed = 0
    last_id = 0
    batch_num = 0
    select_cols = [id_column] + list(text_columns)
    # Start with a smaller limit when filtering by null embedding to avoid statement timeout on large tables
    fetch_limit = min(batch_size, 80) if empty_only else batch_size

    while True:
        batch_num += 1
        query = (
            supabase.table(table)
            .select(*select_cols)
            .gt(id_column, last_id)
            .order(id_column)
            .limit(fetch_limit)
        )
        if empty_only:
            query = query.is_("embedding", "null")
        try:
            result = query.execute()
        except Exception as e:
            if _is_statement_timeout(e):
                fetch_limit = max(25, fetch_limit // 2)
                logger.warning(
                    "Statement timeout (57014) on %s select, retrying with fetch_limit=%s",
                    table, fetch_limit,
                )
                batch_num -= 1
                continue
            raise
        rows = result.data if hasattr(result, "data") else []
        if not rows:
            break
        # After a successful fetch, allow slightly larger batches (up to batch_size) to speed up
        if fetch_limit < batch_size:
            fetch_limit = min(batch_size, fetch_limit + 20)

        texts = []
        indices = []
        for i, r in enumerate(rows):
            t = (r.get(primary) or "").strip()
            for fb in fallbacks:
                if not t:
                    t = (r.get(fb) or "").strip()
            if t:
                texts.append(t)
                indices.append(i)
            else:
                logger.warning("%s %s=%s has no text, skipping", table, id_column, r.get(id_column))

        if not texts:
            last_id = max(r[id_column] for r in rows)
            processed += len(rows)
            continue

        t0 = time.monotonic()
        embeddings = await get_embeddings_parallel(
            texts, embedding_concurrency, embedding_max_texts_per_request
        )
        t_embed = time.monotonic() - t0
        if embeddings is None:
            failed += len(rows)
            last_id = max(r[id_column] for r in rows)
            processed += len(rows)
            logger.warning("Batch %s %s: get_embeddings failed", table, batch_num)
            continue
        if len(embeddings) != len(texts):
            logger.error("Embedding count mismatch %s batch %s", table, batch_num)
            failed += len(rows)
            last_id = max(r[id_column] for r in rows)
            processed += len(rows)
            continue

        sem = asyncio.Semaphore(update_concurrency)
        loop = asyncio.get_event_loop()

        async def do_update(idx: int, emb_idx: int) -> bool:
            async with sem:
                row = rows[idx]
                emb_list = embeddings[emb_idx].tolist()
                if executor:
                    return await loop.run_in_executor(
                        executor,
                        _sync_update_row,
                        supabase,
                        table,
                        id_column,
                        row[id_column],
                        emb_list,
                    )
                return _sync_update_row(supabase, table, id_column, row[id_column], emb_list)

        t1 = time.monotonic()
        tasks = [do_update(indices[i], i) for i in range(len(indices))]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        t_db = time.monotonic() - t1
        batch_updated = sum(1 for r in results if r is True)
        updated += batch_updated
        failed += len(indices) - batch_updated
        processed += len(rows)
        last_id = max(r[id_column] for r in rows)

        if batch_num % 10 == 0 or batch_num <= 5:
            skipped = len(rows) - len(indices)
            logger.info(
                "%s batch %s: %s rows (%s with text, %s skipped), %s updated (total %s) | embedding %.1fs, db %.1fs",
                table, batch_num, len(rows), len(indices), skipped, batch_updated, processed, t_embed, t_db,
            )
        # Throttle after embedding batch to avoid OpenAI TPM rate limit (1M tokens/min)
        await asyncio.sleep(1.0 if len(indices) > 0 else 0.05)

    return processed, updated, failed


# Table config: (id_column, text_columns). text_columns = (primary, fallback, ...).
TABLE_CONFIG: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "news_articles": ("id", ("summary", "title")),
    "macro_articles": ("id", ("summary", "title")),
    "sec_filing_chunks": ("id", ("text",)),
}


async def run(
    table: str = "all",
    batch_size_articles: int = DEFAULT_BATCH_SIZE_NEWS,
    batch_size_chunks: int = DEFAULT_BATCH_SIZE_CHUNKS,
    update_concurrency: int = DEFAULT_UPDATE_CONCURRENCY,
    embedding_concurrency: int = DEFAULT_EMBEDDING_CONCURRENCY,
    embedding_max_texts_per_request: int = DEFAULT_EMBEDDING_MAX_TEXTS_PER_REQUEST,
    parallel_tables: bool = False,
    empty_only: bool = True,
) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY is not set. Set it to run this backfill.")
        return
    from backend.services.embedding_service import get_embedding_service
    svc = get_embedding_service()
    if not svc.available:
        logger.error("Embedding service is not available (missing OPENAI_API_KEY?).")
        return
    logger.info("Embedding model: OpenAI (text-embedding-3-small)")
    logger.info("Mode: %s", "empty-only (only rows where embedding IS NULL)" if empty_only else "all rows (re-embed everything)")

    supabase = get_supabase_client()
    executor = ThreadPoolExecutor(max_workers=64)

    tables_to_run = list(TABLE_CONFIG.keys()) if table == "all" else [table]
    if table != "all" and table not in TABLE_CONFIG:
        logger.error("Unknown table %s. Use one of: %s", table, ", ".join(TABLE_CONFIG))
        return

    total_processed = total_updated = total_failed = 0

    async def run_one(tab: str, id_col: str, text_cols: Tuple[str, ...], bs: int) -> Tuple[int, int, int]:
        return await backfill_table(
            supabase, tab, id_col, text_cols, bs, update_concurrency, embedding_concurrency,
            embedding_max_texts_per_request, executor=executor, empty_only=empty_only,
        )

    if parallel_tables and table == "all":
        tasks = []
        for tab in tables_to_run:
            id_col, text_cols = TABLE_CONFIG[tab]
            bs = batch_size_chunks if tab == "sec_filing_chunks" else batch_size_articles
            tasks.append(run_one(tab, id_col, text_cols, bs))
        results = await asyncio.gather(*tasks)
        for tab, (p, u, f) in zip(tables_to_run, results):
            total_processed += p
            total_updated += u
            total_failed += f
            logger.info("%s done: processed=%s updated=%s failed=%s", tab, p, u, f)
    else:
        for tab in tables_to_run:
            id_col, text_cols = TABLE_CONFIG[tab]
            bs = batch_size_chunks if tab == "sec_filing_chunks" else batch_size_articles
            processed, updated, failed = await run_one(tab, id_col, text_cols, bs)
            total_processed += processed
            total_updated += updated
            total_failed += failed
            logger.info("%s done: processed=%s updated=%s failed=%s", tab, processed, updated, failed)

    executor.shutdown(wait=True)
    logger.info("Backfill new model summary: processed=%s updated=%s failed=%s", total_processed, total_updated, total_failed)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Re-embed all rows with OpenAI text-embedding-3-small (1536-dim). Run DB migration first.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--table", type=str, default="all", choices=["all", "news_articles", "macro_articles", "sec_filing_chunks"], help="Table to backfill (default: all)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE_NEWS, help="Batch size for articles (default: %s)" % DEFAULT_BATCH_SIZE_NEWS)
    parser.add_argument("--batch-size-chunks", type=int, default=DEFAULT_BATCH_SIZE_CHUNKS, help="Batch size for sec_filing_chunks (default: %s)" % DEFAULT_BATCH_SIZE_CHUNKS)
    parser.add_argument("--update-concurrency", type=int, default=DEFAULT_UPDATE_CONCURRENCY, help="Parallel DB updates per batch (default: %s)" % DEFAULT_UPDATE_CONCURRENCY)
    parser.add_argument("--embedding-concurrency", type=int, default=DEFAULT_EMBEDDING_CONCURRENCY, help="Parallel embedding requests per batch (default: %s)" % DEFAULT_EMBEDDING_CONCURRENCY)
    parser.add_argument("--embedding-max-texts", type=int, default=DEFAULT_EMBEDDING_MAX_TEXTS_PER_REQUEST, help="Max texts per single API request (default: %s)" % DEFAULT_EMBEDDING_MAX_TEXTS_PER_REQUEST)
    parser.add_argument("--parallel-tables", action="store_true", help="When --table all, run the three tables concurrently")
    parser.add_argument("--all", dest="reembed_all", action="store_true", help="Process all rows (re-embed everything). Default: only rows where embedding IS NULL.")
    args = parser.parse_args()
    asyncio.run(run(
        table=args.table,
        batch_size_articles=args.batch_size,
        batch_size_chunks=args.batch_size_chunks,
        update_concurrency=args.update_concurrency,
        embedding_concurrency=args.embedding_concurrency,
        embedding_max_texts_per_request=args.embedding_max_texts,
        parallel_tables=args.parallel_tables,
        empty_only=not args.reembed_all,
    ))
