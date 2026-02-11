"""
Backfill embeddings for macro_kb_chunks where embedding IS NULL.

Usage:
  python -m backend.scripts.backfill_macro_kb_embeddings
  python -m backend.scripts.backfill_macro_kb_embeddings --limit 500
  python -m backend.scripts.backfill_macro_kb_embeddings --book-id 123456

Requires OPENAI_API_KEY. Processes in batches of 50; updates each chunk by id.
"""
import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.storage.embedding_utils import get_embeddings
from backend.storage.macro_kb_query import get_chunks_with_null_embedding
from backend.storage.supabase_client import get_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 50


async def backfill_batch(supabase, chunks: list) -> int:
    """Embed one batch of chunks and update DB; return count updated."""
    if not chunks:
        return 0
    texts = [c["text"] or "" for c in chunks]
    emb_arr = await get_embeddings(texts)
    if emb_arr is None or emb_arr.shape[0] != len(chunks):
        logger.warning("Embedding batch failed for %d chunks", len(chunks))
        return 0
    updated = 0
    for i, c in enumerate(chunks):
        if i >= emb_arr.shape[0]:
            break
        vec = emb_arr[i].tolist()
        try:
            supabase.table("macro_kb_chunks").update({"embedding": vec}).eq("id", c["id"]).execute()
            updated += 1
        except Exception as e:
            logger.warning("Update failed for chunk id=%s: %s", c.get("id"), e)
    return updated


async def run_backfill(limit=None, book_id=None):
    """Load chunks with null embedding, process in batches, return stats."""
    supabase = get_supabase_client()
    chunks = get_chunks_with_null_embedding(supabase, limit=limit, book_id=book_id)
    total = len(chunks)
    if total == 0:
        logger.info("No macro_kb_chunks with null embedding")
        return {"total_null": 0, "updated": 0}
    logger.info("Found %d chunks with null embedding", total)
    updated = 0
    for start in range(0, total, BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        n = await backfill_batch(supabase, batch)
        updated += n
        logger.info("Batch %d–%d: %d updated (total updated so far: %d)", start, start + len(batch), n, updated)
    return {"total_null": total, "updated": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill embeddings for macro_kb_chunks where embedding IS NULL")
    parser.add_argument("--limit", type=int, default=None, help="Max chunks to process (default: all)")
    parser.add_argument("--book-id", type=int, default=None, help="Only chunks for this book_id")
    args = parser.parse_args()
    stats = asyncio.run(run_backfill(limit=args.limit, book_id=args.book_id))
    logger.info("Backfill result: %s", stats)
    if stats.get("total_null", 0) > 0 and stats.get("updated", 0) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
