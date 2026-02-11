# News Pipeline

The active pipeline is the **overnight pipeline** (`backend/pipeline/overnight_pipeline/runner.py`).
See **`backend/pipeline/overnight_pipeline/README.md`** for the algorithm and run instructions.

---

## Shared Modules

These modules are used by the overnight pipeline runner:

| File | Role |
|------|------|
| **long_story_service.py** | `find_similar_long_story` (embedding), `add_article_to_long_story` (link + cap), `refresh_long_story_content` (LLM updates title/summary/embedding), `create_long_story` (historical articles; title/theme/summary from LLM). |
| **maybe_merge_or_create_long_story.py** | Merge into or create a long story: find similar by embedding → merge or RAG 5-year + rerank + create. |
| **news_collection.py** | `collect_todays_news` (AV/Massive/Gemini flags), `store_news_with_embeddings`; optional existing articles for dedup. |
| **rag_retrieval.py** | `retrieve_similar_news` (multi-ticker, exclude IDs, date window), `extract_tickers_from_article`, `get_related_tickers`. |
| **rerank.py** | Cross-encoder rerank, `rerank_top_n_recent`, `rerank_top_n_history`, `select_top_sorted_by_date`. |
| **store_embed_data.py** | Task 1 style collect+store+embed for all tickers; macro news; filing update. |
| **filing_fetch.py** / **filing_chunking.py** | Fetch full text from SEC EDGAR; chunk for `sec_filing_chunks`. Overnight pipeline uses **overnight_pipeline/filing_link.py** for per-filing chunk similarity. |

---

## Key Tables

| Table | Purpose |
|-------|---------|
| `news_articles` | All collected articles with embeddings |
| `long_stories` | Long-form narrative storylines (one per ticker+theme) |
| `long_story_article_links` | Article-to-long-story links |
| `stories` | Overnight pipeline story clusters |
| `story_article_links` | Article-to-story links |

---

## Configuration (relevant)

| Config | Purpose |
|--------|--------|
| `RAG_TOP_K_CANDIDATES` | Max candidates retrieved before rerank. |
| `RERANK_MODEL` | Cross-encoder model name. |
| `LONG_STORY_DAYS` | Long-story retrieval window in days (default 5 years). |
| `LONG_STORY_SIMILARITY_THRESHOLD` | Min cosine similarity to merge into existing long story. |
| `MAX_LONG_STORY_ARTICLES` | Max articles linked per long story. |
| `MIN_LONG_STORY_ARTICLES` | Minimum useful articles for `create_long_story` to insert. |
| `PIPELINE_TICKER_CONCURRENCY` | Max tickers processed in parallel. |

---

## Macro Digest

The **macro digest** produces **8 daily topic briefs** and an optional **impact report**.
See the macro module (`backend/macro/`) for details.

| Endpoint | Description |
|----------|-------------|
| **GET /macro/daily?date=YYYY-MM-DD** | List 8 topic briefs. Add `full=true` for details. |
| **GET /macro/daily/{date}/impact** | Get impact report for date. |
| **POST /macro/daily/{date}/impact** | Generate (and cache) impact report. |
