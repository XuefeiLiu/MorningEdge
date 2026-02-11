"""
Backfill embedding column for the story table (overnight pipeline stories).

Selects story rows where embedding IS NULL; builds text from title + topics (theme) + summary
(same as runner and long-story similarity); batch embeds via EmbeddingService; updates each row.

Run after applying the migration that adds story.embedding (e.g. add_story_embedding_column).

Usage:
  python -m backend.scripts.backfill_story_embeddings [--batch-size N]
"""
import asyncio
import logging
from typing import Any, Dict

from backend.storage.supabase_client import get_supabase_client

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.ERROR)

BATCH_SIZE = 50


def _story_text(row: Dict[str, Any]) -> str:
    """Same text as runner: title + theme (topics) + summary for embedding."""
    title = (row.get("title") or "").strip()
    summary = (row.get("summary") or "").strip()
    topics = row.get("topics") or []
    theme = " ".join(topics) if isinstance(topics, list) else (str(topics) if topics else "")
    return "\n".join(filter(None, [title, theme, summary])) or title or summary or ""


async def backfill_story_embeddings(
    supabase,
    batch_size: int = BATCH_SIZE,
) -> int:
    """
    Fetch story rows where embedding IS NULL, build text, batch embed, update.
    Returns count of rows updated.
    """
    from backend.services.embedding_service import get_embedding_service

    emb_svc = get_embedding_service()
    updated = 0
    while True:
        try:
            q = (
                supabase.table("story")
                .select("id, title, summary, topics")
                .is_("embedding", "null")
                .order("id")
                .range(0, batch_size - 1)
            )
            result = q.execute()
        except Exception as e:
            if "column" in str(e).lower() and "embedding" in str(e).lower():
                logger.warning("story table has no embedding column: %s", e)
                return 0
            raise
        rows = result.data or []
        if not rows:
            break
        texts = []
        valid = []
        for r in rows:
            t = _story_text(r)
            if t and t.strip():
                texts.append(t.strip())
                valid.append(r)
            else:
                logger.debug("Skip story id=%s (no text)", r.get("id"))
        if not texts:
            # All rows in batch had no text; use placeholder so we don't loop forever
            empty_emb = await emb_svc.get_embeddings(["empty story"])
            if empty_emb is not None and len(empty_emb) > 0:
                vec = empty_emb[0].tolist() if hasattr(empty_emb[0], "tolist") else list(empty_emb[0])
            else:
                vec = [0.0] * 1536
            for r in rows:
                try:
                    supabase.table("story").update({"embedding": vec}).eq("id", r["id"]).execute()
                    updated += 1
                except Exception as e:
                    logger.debug("Update story id=%s (empty) failed: %s", r.get("id"), e)
            logger.info("story: %d row(s) had no text, set placeholder embedding", len(rows))
        else:
            embeddings = await emb_svc.get_embeddings(texts)
            if embeddings is None:
                logger.warning("Embedding call failed for story batch, skipping %d rows", len(rows))
                await asyncio.sleep(1.0)
                continue
            if len(embeddings) != len(valid):
                logger.warning("Embedding count mismatch for story: %d vs %d", len(embeddings), len(valid))
                await asyncio.sleep(0.5)
                continue
            for i, r in enumerate(valid):
                try:
                    vec = embeddings[i].tolist() if hasattr(embeddings[i], "tolist") else list(embeddings[i])
                    supabase.table("story").update({"embedding": vec}).eq("id", r["id"]).execute()
                    updated += 1
                except Exception as e:
                    logger.debug("Update story id=%s failed: %s", r.get("id"), e)
        logger.info("story: updated %d so far (batch size %d)", updated, len(rows))
        if len(rows) < batch_size:
            break
        await asyncio.sleep(0.3)
    return updated


async def run_async(batch_size: int = BATCH_SIZE) -> None:
    supabase = get_supabase_client()
    try:
        n = await backfill_story_embeddings(supabase, batch_size=batch_size)
        logger.info("story: %d row(s) updated with embedding", n)
    except Exception as e:
        logger.exception("story backfill failed: %s", e)
        raise
    logger.info("Backfill story embeddings done.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Backfill embedding for story table (overnight stories).")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Batch size")
    args = parser.parse_args()
    asyncio.run(run_async(batch_size=args.batch_size))


if __name__ == "__main__":
    main()
