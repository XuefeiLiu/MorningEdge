# Overnight Pipeline

Story-first overnight risk pipeline: **run store/embed data first** (Task1-style collect+store with embeddings), then **anchor-based clustering** (anchors = Gemini-sourced articles), **one LLM call per cluster** for title/summary/risk fields, **conditional filing linkage**, persist to `story` and link tables, and optionally **long-story merge/create** for stories that deserve a long-form narrative.

---

## Pipeline algorithm (detail)

The runner (`runner.py`) runs the following steps in order.

### 1. Store/embed data (optional)

Unless `--skip-store-embed` is set, the pipeline runs **store/embed** first via `run_store_embed_data` (same as Task1): macro news (last 24h), optional macro digest, collect+store news with embeddings for all tickers, including **Gemini** so anchor seeds exist in `news_articles`. Optional filing update (10-K/10-Q fetch, chunk, embed) can be enabled separately.

### 2. Article window and anchors

- **Time windows**
  - **Gemini (anchor source)**: articles with `created_at` in the last **3 hours** (ingestion time); must be Gemini-sourced (`collector == "gemini"` or `source == GEMINI_GENERATED_SOURCE`).
  - **Other sources**: articles with `published_at` in the last **18 hours** (AV, Massive, etc.).
- **Anchor seeds**: every Gemini-sourced article in that 3h window is one **anchor**. All other articles in the combined set are **non-anchor**.
- If `--tickers` is provided, the combined article list is filtered to those tickers.

### 3. Embeddings

- For each anchor and each non-anchor article, the pipeline uses the existing `embedding` from the DB if present; otherwise it embeds `title + summary` via the shared embedding service.
- Outputs: `anchor_ids`, `anchor_embeddings`, `non_anchor_ids`, `non_anchor_embeddings`, and an `id_to_article` map for later steps.

### 4. Clustering (`clustering.py`)

Two-phase clustering:

1. **Seeded clusters**
   - For each **non-anchor** article, compute cosine similarity to every anchor.
   - If the **best similarity ≥ `T_ASSIGN`** (default `0.68`, env `OVERNIGHT_T_ASSIGN`), assign that article to that anchor’s cluster.
   - Each anchor gets one cluster; cluster members = anchor + all assigned articles. Clusters are labeled `cluster_type: "seeded"`.

2. **Discovered clusters**
   - Articles that were **not** assigned to any anchor are “unmatched.”
   - Among unmatched articles, build a graph: edge between two articles if their **cosine similarity ≥ `T_GRAPH`** (default `0.62`, env `OVERNIGHT_T_GRAPH`).
   - **Connected components** of this graph form “discovered” clusters (no anchor). Label: `cluster_type: "discovered"`.
   - Single unmatched articles become one-article discovered clusters.

Result: a list of clusters; each has `cluster_type`, `anchor_article_id` (or `None`), and `article_ids`.

### 5. LLM per cluster (`story_llm.py`)

- For each cluster with at least one article, one **OpenAI** call is made.
- **Input**: anchor title/summary (if seeded), all member articles (id, title, summary, source, published_at), asof_date, ticker (from first article or anchor).
- **Output**: strict JSON with title, summary, topics, session_label, risk fields (risk_horizon, prob_move_ge_1pct, direction_bias, etc.), and optional filing fields (is_filing_related, filing_form_types, estimated_filing_date_et). LLM may return `omit_story: true` if the cluster is not meaningfully about the ticker.
- **Session label**: if the latest article’s `published_at` in ET falls 9am–4pm on a US business day, the pipeline forces `INTRADAY`; otherwise the LLM chooses OVERNIGHT / INTRADAY / MIXED.

### 6. Persist story and article links

- For each cluster that received a valid story payload (no `omit_story`):
  - **Story row**: `insert_story` writes to `story` (asof_date, title, summary, topics, risk fields, ticker, cluster_type, cluster_size, pipeline_version, prompt_version, seed from sorted article_ids, **embedding** from title+topics+summary).
  - **Article links**: `insert_story_article_links` writes `story_article_link` with role `ANCHOR` for the anchor article and `SUPPORTING` for others.

### 7. Conditional filing link

- If the story payload has **`is_filing_related == true`** and a ticker:
  - **Most recent filing**: `get_most_recent_filing(supabase, ticker, form_types, max_filed_date)` returns the latest `sec_filings` row by `filed_date` (optionally filtered by form_type and `filed_date <= story date`).
  - If a filing is found: embed the story summary (or title), retrieve **top-1 chunk** from that filing by similarity (`get_top_chunks_for_filing`), then `insert_story_filing_link` with filing_id, link type `MOST_RECENT`, optional chunk_id and score.

### 8. Long-story flow (optional, default on)

Unless `--skip-long-story` is set:

- For each **persisted** story:
  - **Non-Gemini articles only**: the cluster’s `article_ids` are filtered to rows that are **not** Gemini-generated (only real news articles are used for long-story merge/create).
  - **Gate**: `deserves_long_story` LLM (`long_story_gate.py`) is called with the story’s title, summary, and topics; it returns whether the story deserves a long-form narrative (strategy shifts, multi-month potential vs one-off/short-term).
  - If **true**: `maybe_merge_or_create_long_story` is called (see below). It either **merges** into an existing long story or **creates** a new one.

Returned **stats** include: store/embed metrics (if run), `stories_created`, `links_created`, `filing_links`, `long_storylines_created`, `long_storylines_updated`.

---

### maybe_merge_or_create_long_story (detail)

The overnight runner calls this with the **story_id path**: it passes `story_id`, `story_embedding` (from the persisted story row), ticker, the list of **(article_id, article)** for non-Gemini cluster articles, `tickers_to_query` (ticker + related tickers), and LLM client/model. The function lives in `backend/pipeline/maybe_merge_or_create_long_story.py` and is shared with the legacy pipeline (which can also use a **short_storyline_id** path and build the embedding from the short storyline row).

**Behavior:**

1. **Embedding**  
   - **Story_id path** (overnight): use the provided `story_embedding`.  
   - **Short_storyline_id path** (legacy): load the short storyline’s title, theme, summary and embed that text.

2. **Find similar long story**  
   `find_similar_long_story(supabase, ticker, embedding)` (in `long_story_service`) returns the most similar long story for that ticker by cosine similarity above threshold, or `None`.

3. **If a similar long story exists (merge)**  
   - For each article in the list, `add_article_to_long_story(supabase, long_story_id, ticker, article_id, article_ticker)` inserts/updates `long_story_article_links` (and enforces max articles per long story).  
   - Update the long story’s `last_updated_at`.  
   - `refresh_long_story_content(supabase, long_story_id, llm_client, llm_model)` re-runs the LLM over all linked articles to refresh title, summary, and embedding.  
   - Increment `delta["storylines_updated"]`, return the long_story_id.

4. **If no similar long story (create)**  
   - **RAG**: `retrieve_similar_news(supabase, tickers_to_query, embedding, exclude_article_ids=set of all story article IDs, limit=RAG_TOP_K_CANDIDATES, start_date=now - LONG_STORY_DAYS, end_date=now)`. Results are filtered so none of the current story’s articles are included.  
   - **Rerank**: `rerank(story_query_text, similar_long, RAG_TOP_K_CANDIDATES)` where `story_query_text` is the concatenation of title+summary of all story articles; then `select_top_sorted_by_date(reranked_long, max_articles=rerank_top_n_history())`.  
   - **Guards**: If no selected articles, or all selected articles fall in the same ISO week, skip creation and return.  
   - **Historical set**: `historical_articles = story_article_dicts + selected_long` (current story articles plus RAG-selected past articles).  
   - **Create**: `create_long_story(supabase, ticker, historical_articles, llm_client, model=llm_model)` inserts one row in `long_stories` and links in `long_story_article_links`. Title, theme, and summary come only from the LLM response. Then the new long story’s embedding is set from its title/theme/summary.  
   - Increment `delta["storylines_created"]`, return `None` (the function returns a long_story_id only when it merged).

**Tables**: `long_stories`, `long_story_article_links`. Helpers: `long_story_service` (`find_similar_long_story`, `add_article_to_long_story`, `refresh_long_story_content`, `create_long_story`), `rag_retrieval.retrieve_similar_news`, `rerank.rerank` / `select_top_sorted_by_date`.

---

## Run

From project root (with `.env` and dependencies installed):

```bash
# Full run: store/embed (collect+store for all tickers, including Gemini) then overnight story pipeline
python -m backend.pipeline.overnight_pipeline.runner --asof-date 2025-02-05
python -m backend.pipeline.overnight_pipeline.runner --asof-date 2025-02-05 --tickers AAPL,MSFT

# Skip store/embed if news_articles is already populated for the day
python -m backend.pipeline.overnight_pipeline.runner --asof-date 2025-02-05 --skip-store-embed

# Skip long-story merge/create (only create overnight stories and links)
python -m backend.pipeline.overnight_pipeline.runner --asof-date 2025-02-05 --skip-long-story
```

Or call from code:

```python
from backend.pipeline.overnight_pipeline import run_overnight_pipeline
import asyncio
stats = asyncio.run(run_overnight_pipeline(asof_date=date(2025, 2, 5)))
# stats includes store_embed (tickers_processed, articles_stored, ...) and stories_created, links_created, etc.
```

## Store/embed data (single file)

`store_embed_data.py` lives in the **pipeline** folder (`backend/pipeline/store_embed_data.py`). It implements full Task1: macro news (last 24h), optional macro digest (raw → topic briefs → daily summary), collect+store news with embeddings per ticker, and optional filing update (new 10-K/10-Q fetch, chunk, embed, store). Used by both `pipeline.py` (Task1) and the overnight runner. The overnight runner runs it first (with `include_gemini=True`) so `news_articles` is populated including Gemini for anchor seeds before clustering.

## Dependencies

- `OPENAI_API_KEY` for embeddings and story LLM.
- Supabase with `story`, `story_article_link`, `story_filing_link`, `story_evidence_chunk_link` (migration applied).
