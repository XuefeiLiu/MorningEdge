# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Morning Edge is a US stock pre-market briefing system. It collects overnight news from 15+ sources, filters with AI (OpenAI/Gemini), clusters articles into storylines via embedding similarity, generates trading signals, and presents everything through a React dashboard. Backend is Python/FastAPI with Supabase (PostgreSQL + pgvector); frontend is React 19 + TypeScript + Vite.

## Commands

### Backend
```bash
# Run API server
python -m uvicorn backend.main:app --reload --port 8000

# Run tests
pytest backend/tests/ -v

# Run a single test
pytest backend/tests/test_helpers.py -v -k "test_name"

# Run overnight pipeline for a date
python -m backend.pipeline.overnight_pipeline.runner --asof-date 2025-02-08

# Populate stocks table
python backend/storage/stocks_main.py

# Fetch/store news articles
python backend/storage/news_articles_main.py --start-date 2026-01-20 --end-date 2026-01-24

# Backfill embeddings
python -m backend.scripts.backfill_embeddings --batch-size 1000
```

### Frontend
```bash
cd frontend
npm install
npm run dev        # Dev server on port 3000
npm run build      # Production build
```

### Configuration
```bash
cp .env.example .env   # Then add API keys
```
Required: `SUPABASE_URL`, `DB_API_KEY`, `OPENAI_API_KEY`. Optional: `GEMINI_API_KEY`, `ALPHA_VANTAGE_API_KEY`, and many others (see `.env.example`).

## Architecture

### Backend (`backend/`)

- **`main.py`** — FastAPI app entry point (port 8000). Registers 7 routers.
- **`config.py`** — All env vars, news source registry, thresholds, keywords.
- **`models.py`** — Pydantic models (NewsItem, MacroEvent, BriefingReport, etc.).
- **`routers/`** — API endpoints: briefing, news, stories, macro, watchlist, stocks, system.
- **`services/`** — Core business logic:
  - **`collectors/`** — 15 data source collectors inheriting from `BaseCollector` or `RSSCollector`. Registered via `news_registry.py`.
  - **`news_filters/`** — `KeywordRelevanceFilter`, `OpenAIFilter`, `GeminiFilter` with `FilterFactory`. AI filters fall back to keyword filtering.
  - **`news_aggregator.py`** — Parallel multi-source collection with per-collector timeouts.
  - **`embedding_service.py`** — OpenAI `text-embedding-3-small` (1536-dim, pgvector).
  - **`briefing.py`** — `BriefingGenerator` and `TimeWindowCalculator`.
- **`pipeline/`** — Story generation:
  - **`overnight_pipeline/`** (current, recommended) — Anchor-based clustering: extract Gemini anchors → 2-phase clustering (seeded T_ASSIGN≥0.68, discovered T_GRAPH≥0.62) → one LLM call per cluster → persist stories → optional filing link + long-story merge.
  - Legacy pipeline modules (per-article RAG) still exist but prefer overnight pipeline for new runs.
- **`macro/`** — Macro digest: 8 topics (FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy, Monetary Policy, Trump), KB ingest, impact analysis.
- **`storage/`** — Supabase read/write. Follows `*_save.py` / `*_query.py` / `*_main.py` pattern per table.
- **`scripts/`** — Backfills, migrations, cleanup utilities.
- **`utils/`** — Helpers, US market calendar.

### Frontend (`frontend/`)

- **`App.tsx`** — Root: Login/Dashboard routing.
- **`api.ts`** — Centralized API client (`fetchJSON`, `postJSON`). API base from `VITE_API_URL`.
- **`types.ts`** — TypeScript type definitions matching backend models.
- **`components/`** — Dashboard, StockDetail (largest component), StockCard, MacroView, StorylineTable, LongStoryTimeline, TradingViewChart, AskChat, etc.
- **`i18n/`** — English + Chinese (Simplified) with locale context provider.

### Key Patterns

**Database IDs**: All new IDs use `_string_id_to_bigint(string_id)` for deterministic bigint PKs. Import from `backend.storage.news_articles_save` (general) or `backend.storage.macro_id_utils` (macro tables). Never use auto-increment or random IDs when a natural string key exists.

**Collector pattern**: Inherit `BaseCollector` (API) or `RSSCollector` (RSS). Register in `BriefingGenerator`, `NEWS_SOURCES` config, and `collectors/__init__.py`. Use `mark_unavailable()` for error states.

**Timezone handling**: Backend stores/returns UTC. Frontend converts to local time at display using `Intl.DateTimeFormat` without a fixed `timeZone` option. Never mix UTC and local display in the same path.

**RAG retrieval**: Default is pgvector (Supabase). When `ELASTICSEARCH_URL` + `RAG_USE_ELASTICSEARCH=true`, uses hybrid BM25 + kNN. Auto-falls back to Supabase if ES unavailable.

**Storyline/article IDs**: Passed as strings end-to-end (API → frontend) to preserve bigint precision in JavaScript.

## Testing

pytest with `asyncio_mode = "auto"`. Tests in `backend/tests/`. Config: `pyproject.toml`.

## CI/CD

GitHub Actions workflow `daily_pipeline.yml` runs the overnight pipeline on a schedule. Required secrets: `SUPABASE_URL`, `DB_API_KEY`, `OPENAI_API_KEY`, plus data source API keys.
