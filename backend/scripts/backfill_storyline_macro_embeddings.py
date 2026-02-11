"""
Backfill embedding column for long_stories and macro brief tables.

Fetches rows without embedding; builds text from title + theme + summary (or macro fields);
batch embeds via EmbeddingService; updates rows.

Usage:
  python -m backend.scripts.backfill_storyline_macro_embeddings [--batch-size N] [--skip-macro]
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from backend.storage.supabase_client import get_supabase_client

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.ERROR)

BATCH_SIZE = 50


def _storyline_text(row: Dict[str, Any]) -> str:
    title = (row.get("title") or "").strip()
    theme = (row.get("canonical_theme") or "").strip()
    summary = (row.get("summary") or "").strip()
    return "\n".join(filter(None, [title, theme, summary])) or title or theme or ""


def _macro_brief_text(row: Dict[str, Any]) -> str:
    title = (row.get("title") or "").strip()
    summary = (row.get("summary") or "").strip()
    bullets = row.get("summary_bullets")
    if isinstance(bullets, list):
        summary += "\n" + "\n".join(str(b) for b in bullets)
    elif bullets:
        summary += "\n" + str(bullets)
    return "\n".join(filter(None, [title, summary])) or ""


def _macro_summary_text(row: Dict[str, Any]) -> str:
    title = (row.get("title") or "").strip()
    summary = (row.get("summary") or "").strip()
    bullets = row.get("summary_bullets")
    if isinstance(bullets, list):
        summary += "\n" + "\n".join(str(b) for b in bullets)
    elif bullets:
        summary += "\n" + str(bullets)
    return "\n".join(filter(None, [title, summary])) or ""


async def backfill_table(
    supabase: Any,
    table: str,
    select_cols: str,
    id_col: str,
    text_fn: callable,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Fetch rows where embedding is null, embed, update. Returns count updated.

    Uses limit-only pagination (no offset): each batch fetches the next N null rows,
    updates them, then the next iteration gets the next N null rows. This avoids
    the result set shrinking as we update rows, which would skip rows with a fixed offset.
    """
    from backend.services.embedding_service import get_embeddings

    updated = 0
    while True:
        try:
            q = (
                supabase.table(table)
                .select(select_cols)
                .is_("embedding", "null")
                .order(id_col)
                .range(0, batch_size - 1)
            )
            result = q.execute()
        except Exception as e:
            if "column" in str(e).lower() and "embedding" in str(e).lower():
                logger.warning("Table %s has no embedding column, skip: %s", table, e)
                return 0
            raise
        rows = result.data or []
        if not rows:
            break
        texts = []
        valid = []
        for r in rows:
            t = text_fn(r)
            if t and t.strip():
                texts.append(t.strip())
                valid.append(r)
            else:
                logger.debug("Skip row id=%s (no text)", r.get(id_col))
        if not texts:
            # All rows in batch had no text; use one "empty" embedding so we don't loop forever
            empty_emb = await get_embeddings(["empty storyline"])
            if empty_emb is not None and len(empty_emb) > 0:
                vec = empty_emb[0].tolist()
                for r in rows:
                    try:
                        supabase.table(table).update({"embedding": vec}).eq(id_col, r[id_col]).execute()
                        updated += 1
                    except Exception as e:
                        logger.debug("Update %s id=%s (empty) failed: %s", table, r.get(id_col), e)
            else:
                # Fallback: zero vector (1536 = text-embedding-3-small)
                vec = [0.0] * 1536
                for r in rows:
                    try:
                        supabase.table(table).update({"embedding": vec}).eq(id_col, r[id_col]).execute()
                        updated += 1
                    except Exception as e:
                        logger.debug("Update %s id=%s (empty) failed: %s", table, r.get(id_col), e)
            logger.info("Table %s: %d row(s) had no text, set placeholder embedding", table, len(rows))
        else:
            embeddings = await get_embeddings(texts)
            if embeddings is None:
                logger.warning("Embedding call failed for table %s batch, skipping %d rows", table, len(rows))
                await asyncio.sleep(1.0)
                continue
            if len(embeddings) != len(valid):
                logger.warning("Embedding count mismatch for %s: %d vs %d", table, len(embeddings), len(valid))
                await asyncio.sleep(0.5)
                continue
            for i, r in enumerate(valid):
                try:
                    supabase.table(table).update({"embedding": embeddings[i].tolist()}).eq(id_col, r[id_col]).execute()
                    updated += 1
                except Exception as e:
                    logger.debug("Update %s id=%s failed: %s", table, r.get(id_col), e)
        logger.info("Table %s: updated %d so far (batch size %d)", table, updated, len(rows))
        if len(rows) < batch_size:
            break
        await asyncio.sleep(0.3)
    return updated


async def run_async(batch_size: int = BATCH_SIZE, skip_macro: bool = False) -> None:
    supabase = get_supabase_client()

    # long_stories
    try:
        n = await backfill_table(
            supabase,
            "long_stories",
            "id, title, canonical_theme, summary",
            "id",
            _storyline_text,
            batch_size=batch_size,
        )
        logger.info("long_stories: %d row(s) updated with embedding", n)
    except Exception as e:
        logger.warning("long_stories backfill failed: %s", e)

    if not skip_macro:
        try:
            n = await backfill_table(
                supabase,
                "macro_daily_briefs",
                "id, title, summary, summary_bullets",
                "id",
                _macro_brief_text,
                batch_size=batch_size,
            )
            logger.info("macro_daily_briefs: %d row(s) updated with embedding", n)
        except Exception as e:
            if "does not exist" in str(e).lower() or "column" in str(e).lower():
                logger.info("macro_daily_briefs skipped: %s", e)
            else:
                logger.warning("macro_daily_briefs backfill failed: %s", e)

        try:
            n = await backfill_table(
                supabase,
                "macro_daily_summary",
                "id, title, summary, summary_bullets",
                "id",
                _macro_summary_text,
                batch_size=batch_size,
            )
            logger.info("macro_daily_summary: %d row(s) updated with embedding", n)
        except Exception as e:
            if "does not exist" in str(e).lower() or "column" in str(e).lower():
                logger.info("macro_daily_summary skipped: %s", e)
            else:
                logger.warning("macro_daily_summary backfill failed: %s", e)

    logger.info("Backfill storyline/macro embeddings done.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Backfill embedding for storylines and macro briefs.")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Batch size per table")
    parser.add_argument("--skip-macro", action="store_true", help="Skip macro_daily_briefs and macro_daily_summary")
    args = parser.parse_args()
    asyncio.run(run_async(batch_size=args.batch_size, skip_macro=args.skip_macro))


if __name__ == "__main__":
    main()
