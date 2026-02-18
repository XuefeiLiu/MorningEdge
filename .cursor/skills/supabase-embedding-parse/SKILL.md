---
name: supabase-embedding-parse
description: Use parse_embedding_from_db when reading embedding columns from Supabase. Supabase/PostgREST returns pgvector as string; normalize to list of floats before sending to Elasticsearch or other consumers.
---

# Supabase embedding: always parse before use

## Rule

**Supabase/PostgREST returns pgvector (and embedding) columns as strings** (e.g. `"[0.1, -0.2, ...]"`), not Python lists. Any code that reads an embedding from Supabase and then uses it (e.g. sends to Elasticsearch, does similarity, or passes to code expecting `List[float]`) must normalize it with `parse_embedding_from_db` first.

- **Input**: Value from a Supabase/PostgREST response for an embedding column (can be `str`, `list`, or `None`).
- **Output**: `List[float]` or `None`; use the result and skip the row if `None`.

This avoids type errors and failed bulk indexes when sending to Elasticsearch (dense_vector expects an array of floats, not a string).

## Import

```python
from backend.storage.embedding_utils import parse_embedding_from_db
```

## When to use

- Reading `embedding` (or any pgvector column) from Supabase in backfill scripts, sync code, or API handlers.
- Building Elasticsearch documents that include an `embedding` field (bulk or single-doc index).
- Any place that receives a row from `news_articles`, `sec_filing_chunks`, `macro_kb_chunks`, `long_stories`, or `story` and uses the embedding.

## Usage pattern

```python
# After fetching row from Supabase (e.g. result.data or .select(...).execute())
embedding = parse_embedding_from_db(row.get("embedding"))
if embedding is None:
    continue  # or skip this doc
# Use embedding (list of floats) for ES, similarity, etc.
es_doc = {..., "embedding": embedding}
```

## Do not

- Pass `row.get("embedding")` directly to Elasticsearch or to code that expects `List[float]`.
- Assume Supabase returns embeddings as lists; it often returns them as JSON strings.
