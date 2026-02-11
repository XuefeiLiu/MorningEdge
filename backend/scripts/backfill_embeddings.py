"""
Backfill script to populate embedding column for existing news articles.
Gets embeddings for summaries (fallback to title if summary is None) and updates the database.

Usage:
  python -m backend.scripts.backfill_embeddings [--batch-size N] [--update-concurrency N]
"""
import asyncio
import logging
import os
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from backend.storage.supabase_client import get_supabase_client
from backend.storage.embedding_utils import get_embeddings

# Configuration for parallel processing
DEFAULT_BATCH_SIZE = 200  # Larger batch for embeddings
DEFAULT_UPDATE_CONCURRENCY = 50  # Number of parallel database updates

# Configure logging
log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Set up root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
root_logger.handlers = []

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(log_format))
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

# Suppress httpx INFO logs
logging.getLogger("httpx").setLevel(logging.ERROR)


def is_retryable_error(error: Exception) -> bool:
    """
    Check if an error is retryable (e.g., Cloudflare 520/522 errors).
    """
    error_str = str(error).lower()
    if '520' in error_str or '522' in error_str:
        return True
    retryable_keywords = [
        'timeout', 'connection', 'network', 'temporary', 'retry', 'rate limit', 'too many requests'
    ]
    return any(keyword in error_str for keyword in retryable_keywords)


async def update_article_with_retry(
    supabase,
    article_id: int,
    embedding: List[float],
    max_retries: int = 3,
    base_delay: float = 1.0
) -> bool:
    """Update an article with embedding, with retry logic for transient errors."""
    for attempt in range(max_retries):
        try:
            update_result = supabase.table("news_articles").update({
                "embedding": embedding
            }).eq("id", article_id).execute()
            if update_result.data:
                if attempt > 0:
                    logger.info(f"Successfully updated article {article_id} on retry attempt {attempt + 1}")
                return True
            else:
                logger.warning(f"No data returned when updating article {article_id}")
                return False
        except Exception as e:
            is_retryable = is_retryable_error(e)
            if attempt < max_retries - 1 and is_retryable:
                delay = base_delay * (2 ** attempt)
                logger.debug(f"Retryable error updating article {article_id} (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                if is_retryable:
                    logger.error(f"Failed to update article {article_id} after {max_retries} attempts: {e}")
                else:
                    logger.error(f"Non-retryable error updating article {article_id}: {e}")
                return False
    return False


async def backfill_embeddings(batch_size: int = DEFAULT_BATCH_SIZE, update_concurrency: int = DEFAULT_UPDATE_CONCURRENCY):
    """Backfill embeddings for all news articles without embeddings."""
    logger.info("=" * 60)
    logger.info("Starting embedding backfill")
    logger.info("=" * 60)
    try:
        supabase = get_supabase_client()
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        return
    try:
        count_result = supabase.table("news_articles").select("id", count="exact").is_("embedding", "null").execute()
        total_count = count_result.count if hasattr(count_result, 'count') else 0
        if total_count == 0:
            logger.info("No articles without embeddings. Backfill complete.")
            return
        logger.info(f"Found {total_count} articles without embeddings")
        logger.info(f"Processing in batches of {batch_size}")
        processed = 0
        updated = 0
        failed = 0
        batch_num = 0
        last_id = 0
        while True:
            batch_num += 1
            logger.info(f"\n--- Processing batch {batch_num} (last_id: {last_id}) ---")
            query = supabase.table("news_articles").select("id, title, summary").is_("embedding", "null").gt("id", last_id).order("id").limit(batch_size)
            result = query.execute()
            articles = result.data if hasattr(result, 'data') else []
            if not articles:
                logger.info("No more articles to process")
                break
            logger.info(f"Fetched {len(articles)} articles for batch {batch_num}")
            texts = []
            article_indices = []
            for idx, article in enumerate(articles):
                text = article.get("summary") or article.get("title")
                if text and text.strip():
                    texts.append(text.strip())
                    article_indices.append(idx)
                else:
                    logger.warning(f"Article {article.get('id')} has no summary or title, skipping")
            if not texts:
                last_id = max(article["id"] for article in articles)
                processed += len(articles)
                continue
            logger.info(f"Getting embeddings for {len(texts)} texts...")
            embeddings = await get_embeddings(texts)
            if embeddings is None:
                failed += len(articles)
                last_id = max(article["id"] for article in articles)
                processed += len(articles)
                continue
            if len(embeddings) != len(texts):
                logger.error(f"Embedding count mismatch: {len(embeddings)} embeddings for {len(texts)} texts")
                failed += len(articles)
                last_id = max(article["id"] for article in articles)
                processed += len(articles)
                continue
            logger.info(f"Updating {len(article_indices)} articles with embeddings...")
            update_semaphore = asyncio.Semaphore(update_concurrency)

            async def update_single_article(article_idx: int, embedding_idx: int):
                async with update_semaphore:
                    article = articles[article_idx]
                    article_id = article["id"]
                    embedding = embeddings[embedding_idx].tolist()
                    return await update_article_with_retry(supabase, article_id, embedding, max_retries=3, base_delay=1.0)

            update_tasks = [update_single_article(article_idx, i) for i, article_idx in enumerate(article_indices)]
            results = await asyncio.gather(*update_tasks, return_exceptions=True)
            batch_updated = sum(1 for r in results if r is True)
            batch_failed = len(results) - batch_updated
            updated += batch_updated
            failed += batch_failed
            logger.info(f"Batch {batch_num} complete: {batch_updated} updated, {batch_failed} failed")
            processed += len(articles)
            last_id = max(article["id"] for article in articles)
            if articles and len(articles) == batch_size:
                await asyncio.sleep(0.5)
            if processed % (batch_size * 5) == 0:
                logger.info(f"Progress: {processed}/{total_count} processed ({100 * processed / total_count:.1f}%)")
        logger.info("=" * 60)
        logger.info("Backfill Summary:")
        logger.info(f"  Total articles processed: {processed}")
        logger.info(f"  Successfully updated: {updated}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Remaining without embeddings: {total_count - updated}")
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Error in backfill: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise
    finally:
        logger.info("Backfill complete")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Backfill embeddings for existing news articles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backend.scripts.backfill_embeddings
  python -m backend.scripts.backfill_embeddings --batch-size 100 --update-concurrency 30
        """
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"Number of articles per batch (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--update-concurrency", type=int, default=DEFAULT_UPDATE_CONCURRENCY, help=f"Parallel database updates (default: {DEFAULT_UPDATE_CONCURRENCY})")
    args = parser.parse_args()
    asyncio.run(backfill_embeddings(batch_size=args.batch_size, update_concurrency=args.update_concurrency))
