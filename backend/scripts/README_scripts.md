# Backend Scripts – Usage

Run all commands from the **project root** (e.g. `Morning_Edge/`). Use `--dry-run` where supported to preview changes.

---

## Storylines & long stories

### backfill_todays_story_impact

Backfill `impact_level` and `impact_score` for **long stories** updated or created today (NULL only). Sets impact_level high and impact_score 0.8. Does not re-run the LLM.

- **impact_score** (0–1): 0.8 for long.
- **impact_level**: derived from impact_score (≥0.7→high, ≥0.3→medium, else low).

```bash
python -m backend.scripts.backfill_todays_story_impact [--dry-run]
```

---

## Cleanup & deduplication

### cleanup_orphan_storylines

Delete **long_stories** that have no rows in `long_story_article_links`.

```bash
python -m backend.scripts.cleanup_orphan_storylines [--dry-run]
```

### remove_duplicate_long_storylines

Remove duplicate long stories (same ticker + similar or exact title/theme). Keeps one per group (smallest id); deletes `long_story_article_links` for duplicates then deletes `long_stories` rows. Default uses LLM for similarity; `--exact-only` matches only exact (ticker+title) or (ticker+canonical_theme).

```bash
python -m backend.scripts.remove_duplicate_long_storylines [--dry-run] [--use-llm] [--exact-only]
```

### remove_long_storylines

Remove **all** long stories: delete from `long_story_article_links` then from `long_stories`.

```bash
python -m backend.scripts.remove_long_storylines [--dry-run]
```

### remove_long_storylines_same_week

Remove long stories whose linked articles are **all from the same ISO week** or that have **no** linked articles. Uses `long_stories` and `long_story_article_links`.

```bash
python -m backend.scripts.remove_long_storylines_same_week [--dry-run]
```

### remove_duplicate_news_articles

Deduplicate news articles (exact or near-duplicate). See script docstrings for options.

---

## Embeddings

### backfill_embeddings

Populate `embedding` for existing `news_articles` (summary or title). Uses batch embedding and configurable concurrency.

```bash
python -m backend.scripts.backfill_embeddings [--batch-size N] [--update-concurrency N]
```

### backfill_storyline_macro_embeddings

Backfill `embedding` for `long_stories` and macro brief tables. Run after migrations that add embedding columns.

```bash
python -m backend.scripts.backfill_storyline_macro_embeddings [--batch-size N] [--skip-macro]
```

### backfill_embeddings_new_model

Re-embed with a new model for tables that already have embeddings (e.g. after model upgrade).

---

## Macro

### backfill_macro_briefs_kb

Backfill macro topic briefs using macro book RAG. For each date in range, re-runs brief generation.

```bash
python -m backend.scripts.backfill_macro_briefs_kb --start 2026-01-01 --end 2026-01-31 [--skip-no-raw]
python -m backend.scripts.backfill_macro_briefs_kb --days 7
```

### backfill_macro_daily_summary

Backfill `macro_daily_summary` from `macro_topic_briefs` for a date range.

### backfill_macro_kb_embeddings

Backfill embeddings for `macro_kb_chunks`.

### ingest_macro_kb

Ingest macro knowledge base (documents → chunks + embeddings).

### run_macro_digest_for_date

Run macro digest pipeline for a single date.

---

## SEC filings & migrations

### backfill_filing_chunks

Backfill `sec_filing_chunks` (and optionally embeddings) for existing SEC filings.

### migrate_sec_filing_ids

One-off migration: rewrite `sec_filings.id` and `sec_filing_chunks.id` to deterministic bigints. **Resumable** (only updates rows not yet migrated).

1. **Drop FK** (Supabase SQL):
   ```sql
   ALTER TABLE public.sec_filing_chunks DROP CONSTRAINT IF EXISTS sec_filing_chunks_filing_id_fkey;
   ```
2. **Run script**:
   ```bash
   python -m backend.scripts.migrate_sec_filing_ids [--dry-run]
   python -m backend.scripts.migrate_sec_filing_ids
   ```
3. **Re-add FK** (SQL):
   ```sql
   ALTER TABLE public.sec_filing_chunks
     ADD CONSTRAINT sec_filing_chunks_filing_id_fkey
     FOREIGN KEY (filing_id) REFERENCES public.sec_filings(id);
   ```

---

## Schema notes

- **Long stories**: live in `long_stories`; links in `long_story_article_links` (`long_story_id`, `article_id`).
  - **UI (Long Story tab)**: Displays all long stories for the ticker with no date filter (1D/2D/3D/custom range do not apply). May add date filtering in the future.
- **Impact**: `impact_score` (0–1) is set at pipeline time (0.8 for long). `impact_level` is derived (≥0.7→high, ≥0.3→medium, else low). Table: `long_stories`; migration: `add_impact_score.sql` if applicable.
