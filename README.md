# Morning Edge - US Stock Pre-Market Briefing System

A comprehensive pre-market briefing system that gathers, filters, and summarizes overnight company news, macroeconomic events, social sentiment, and historical data for your stock watchlist.

## Features

- **Watchlist Management**: Add/remove stocks via the web interface
- **Multi-Source Data Collection**: Aggregates data from multiple free/public sources with parallel collection
- **News Aggregation**: Intelligent multi-source news collection with deduplication and priority-based sorting
- **AI-Powered Filtering**: OpenAI and Gemini-based financial news classification with keyword fallback
- **Smart Filtering**: Relevance scoring, keyword matching, and language-aware duplicate detection
- **Language Support**: English and Chinese news sources with language preservation
- **Impact Tagging**: Automatically categorizes items by impact level (high/medium/low)
- **Trading Signals**: Heuristic-based buy/sell/hold recommendations per stock
- **AI Summaries**: One-click OpenAI/Gemini-powered briefing summaries (optional)
- **Risk Warnings**: Automatic detection of potential risks
- **Database Integration**: Supabase (PostgreSQL) storage for stocks, news articles, and storylines
- **NASDAQ 100 Support**: Built-in NASDAQ 100 ticker list with company information
- **Overnight Pipeline** (current): Anchor-based story pipeline—store/embed data, cluster articles by embedding (Gemini as anchors), one LLM call per cluster for title/summary/risk, optional filing link and long-story merge/create. See `backend/pipeline/overnight_pipeline/README.md`.
- **Legacy storyline pipeline**: Per-article RAG → create short storyline → optional long story (`backend/pipeline/pipeline` and `backend/pipeline/README.md`). Kept for reference; prefer the overnight pipeline for new runs.
- **Macro Digest**: Daily analyst reports (8 topics: FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy, Monetary Policy, Trump) with mechanism, transmission, relative value; macro PDF KB ingest; on-demand impact report (factor mapping, portfolio impact). See `backend/pipeline/README.md` § Macro Digest.
- **Embeddings**: Summary embeddings via OpenAI `text-embedding-3-small` for similarity search and storyline linking
- **Storyline Management**: Deterministic storyline IDs (hash-based, like news articles), CONTEXT linking for historical articles used in summaries
- **MorningEdge Storyline tab**: Stock storylines from the pipeline with a **Supporting articles** overlay (timeline layout, clickable URLs, expandable summaries, relationship badges). Storyline/article IDs are string-based in the API to preserve bigint precision in the frontend. When a storyline has no links yet, the API falls back to recent articles for that ticker.

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm or yarn

### Installation

1. **Clone and navigate to the project**:
   ```bash
   cd Morning_Edge
   ```

2. **Install backend dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install frontend dependencies**:
   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Configure environment variables** (see Configuration section below):
   ```bash
   # Copy and edit the .env file
   cp .env.example .env
   # Add your API keys
   ```

### Database Setup

The system uses Supabase (PostgreSQL) for data storage. Before running the application:

1. **Set up Supabase**:
   - Create a project at https://supabase.com
   - Get your project URL and anon key
   - Add them to your `.env` file

2. **Populate the stocks table**:
   ```bash
   python backend/storage/stocks_main.py
   ```

3. **Fetch and store news articles** (optional, can run periodically):
   ```bash
   python backend/storage/news_articles_main.py
   ```

4. **Run the story pipeline** (optional, processes news into stories): The **overnight pipeline** is the current pipeline (anchor-based clustering, one LLM per cluster). Run it for a given date (e.g. today):
   ```bash
   python -m backend.pipeline.overnight_pipeline.runner --asof-date 2025-02-08
   ```
   See `backend/pipeline/overnight_pipeline/README.md` for options (`--skip-store-embed`, `--tickers`, `--skip-long-story`). A separate GitHub Actions workflow can run the **legacy** pipeline daily (see [Daily Pipeline](#daily-pipeline)).

### Running the Application

1. **Start the backend API** (required for frontend to work):
   ```bash
   python -m uvicorn backend.main:app --reload --port 8000
   ```
   Alternatively, `python -m backend.main` (defaults to port 8000; set `PORT` to use another port). CORS allows `http://localhost:3000` and `http://127.0.0.1:3000` by default; for production deploy, set `CORS_ORIGINS` to your frontend URL(s), comma-separated.

2. **Start the frontend** (in a new terminal):
   ```bash
   cd frontend
   npm run dev
   ```

3. **Access the application**:
   - Frontend: http://localhost:3000
   - API Docs: http://localhost:8000/docs

**Note**: The frontend requires the backend API to be running. The frontend makes API calls to `http://localhost:8000` by default. You can configure a different API URL by setting the `VITE_API_URL` environment variable.

**Note**: The frontend uses React + TypeScript + Vite. If port 3000 is already in use, Vite will automatically use the next available port (3001, 3002, etc.).

### Troubleshooting

- **Python 3.13**: On exit you may see `Exception ignored in: <function _DeleteDummyThreadOnDel.__del__ ...> TypeError: 'NoneType' object does not support the context manager protocol`. This is a [known CPython 3.13 bug](https://github.com/python/cpython/issues/130522) in the threading module during interpreter shutdown. It is harmless (the message says "Exception ignored") and does not affect pipeline or API behavior. You can ignore it, or use Python 3.12 until a patched 3.13.x is released.

## Configuration

1. **Copy the example environment file**:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and add your API keys**:
   ```env
   # Required: Supabase Configuration
   SUPABASE_URL=https://your-project-id.supabase.co
   DB_API_KEY=your_supabase_anon_key_here
   
   # Optional: API Keys (only needed for specific features)
   ALPHA_VANTAGE_API_KEY=your_key_here
   FINANCIAL_DATASETS_API_KEY=your_key_here
   OPENAI_API_KEY=your_key_here
   GEMINI_API_KEY=your_key_here
   MASSIVE_API_KEY=your_key_here
   MARKETAUX_API_KEY=your_key_here
   FMP_API_KEY=your_key_here  # Optional, for NASDAQ 100 ticker API
   
   # Optional: Model Configuration
   OPENAI_MODEL=gpt-4  # Default: gpt-4
   GEMINI_MODEL=gemini-pro-latest  # Default: gemini-pro-latest
   OPENAI_EMBEDDING_MODEL=text-embedding-3-small  # For summary embeddings
   
   # Pipeline (storyline) configuration
   RAG_RETRIEVAL_LIMIT=10   # Top-K similar articles for storyline context
   STORYLINE_UPDATE_MODEL=gpt-4o-mini  # For theme/summary/relationship
   OPENAI_MODEL=gpt-4  # For storyline/relationship LLM calls
   ```

See `.env.example` for detailed descriptions of each variable.

## Data Sources

### Currently Implemented

| Source | Data Type | Status | Notes |
|--------|-----------|--------|-------|
| **SEC EDGAR** | SEC Filings | Active | Free public API, 10 req/sec |
| **FRED** | Macro Data | Active | Free public API |
| **Nasdaq RSS** | Press Releases | Active | Free RSS feeds |
| **Alpha Vantage** | Prices & News | Active | Free tier: 25 req/day |
| **Financial Datasets** | Company News | Active | Requires API key |
| **NewsNow** | Chinese Financial News | Active | Free API, multiple platforms (toutiao, baidu, wallstreetcn, etc.) |
| **Massive API** | Stock News | Active | Requires API key |
| **Marketaux** | Financial News | Active | Requires API key |
| **OpenAI** | AI News Collection | Active | Requires API key, uses GPT models |
| **Gemini** | AI News Collection | Active | Requires API key, uses Gemini models |

### News Source Registry

The system uses a centralized **News Source Registry** (`news_registry.py`) to manage all news collectors with:
- Priority-based ordering
- Enabled/disabled status tracking
- Source metadata (reliability, freshness)
- Per-source configuration (max items, timeouts)

### News Aggregation

The **NewsAggregator** service coordinates multi-source collection:
- Parallel execution with per-collector timeouts (30s default, 90s for NewsNow)
- Global timeout cap (40s) to prevent hanging
- Language-aware deduplication (English/Chinese preserved separately)
- Source priority-based sorting
- Graceful error handling and fallback

### News Filtering System

The system includes a flexible **News Filter** architecture with multiple filter types:

- **KeywordRelevanceFilter**: Keyword-based relevance scoring
- **OpenAIFilter**: AI-powered financial news classification using OpenAI GPT models
- **GeminiFilter**: AI-powered financial news classification using Google Gemini models
- **FilterFactory**: Factory pattern for creating filter instances

All AI filters include automatic keyword fallback when AI services are unavailable.

### Language Support

- **English Sources**: Nasdaq RSS, Alpha Vantage, Financial Datasets, Massive, Marketaux
- **Chinese Sources**: NewsNow platforms (toutiao, baidu, wallstreetcn, thepaper, bilibili, cls, ifeng, tieba, weibo, douyin, zhihu)
- **Language Preservation**: Original language is preserved in UI (no translation)
- **Language-Aware Deduplication**: Items are not deduplicated across languages

### Mock Data Fallback

When real data sources are unavailable or not configured, the system automatically falls back to realistic mock data. This ensures the system works for development and demonstration purposes.

### Placeholder Sources (Future Implementation)

The following data sources have pseudocode placeholders in `backend/services/collectors/mock_data.py`:

#### News Sources
```python
# NewsAPI (requires API key)
# response = await client.get("https://newsapi.org/v2/everything", params={
#     "q": symbol,
#     "from": start_time.isoformat(),
#     "apiKey": NEWS_API_KEY
# })

# Financial RSS feeds
# - https://feeds.finance.yahoo.com/rss/2.0/headline
# - https://www.cnbc.com/id/100003114/device/rss/rss.html
# - https://feeds.bloomberg.com/markets/news.rss
```

#### Sentiment Sources
```python
# Twitter/X API (requires API key)
# Use tweepy or twitter-api-v2 to search for $SYMBOL cashtags

# Reddit API (free with rate limits)
# response = await client.get(
#     f"https://www.reddit.com/r/wallstreetbets/search.json",
#     params={"q": symbol, "sort": "new", "t": "day"}
# )

# StockTwits API
# response = await client.get(
#     f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
# )
```

#### Real-time Price Sources
```python
# Finnhub (free tier available)
# response = await client.get("https://finnhub.io/api/v1/quote", params={
#     "symbol": symbol,
#     "token": FINNHUB_API_KEY
# })

# IEX Cloud (free tier available)
# response = await client.get(
#     f"https://cloud.iexapis.com/stable/stock/{symbol}/quote",
#     params={"token": IEX_API_KEY}
# )
```

## API Endpoints

### Watchlist Management
- `GET /watchlist` - Get current watchlist
- `PUT /watchlist` - Replace watchlist with new symbols
- `POST /watchlist/add?symbol=AAPL` - Add a symbol
- `DELETE /watchlist/{symbol}` - Remove a symbol
- `DELETE /watchlist` - Clear all symbols

### Briefing Generation
- `GET /briefing` - Generate full briefing for watchlist
- `GET /briefing/stock/{symbol}` - Get briefing for single stock

### AI Summaries
- `POST /ai/summarize` - Summarize arbitrary items
- `GET /ai/briefing-summary` - Generate AI summary of current briefing

### News
- `GET /news/stock?ticker=XXX&start_date=...&end_date=...&limit=100` - Get stock news articles for a specific ticker from `news_articles` table
- `GET /news/macro?ticker=XXX&start_date=...&end_date=...&limit=100` - Get macro economic news articles from `macro_articles` table. Returns `primary_topic` and `related_tickers` fields.

### Stocks
- `GET /stocks/nasdaq100` - Get NASDAQ 100 stock list with company names and exchange

### Storylines (deprecated)
- `GET /storylines?ticker=XXX` – **Deprecated.** Returns `[]`. Use `GET /stories` and `GET /long-stories` instead.
- `GET /storylines/{storyline_id}/articles` – **Deprecated.** Returns `[]`. Use long-stories and story APIs for article lists.

**Deprecation**: `story_type` (e.g. `SHORT FILING`) is deprecated for the Dashboard stock card display. Stock cards now show only **Market Open Prediction** when overnight prediction data exists; when there is no prediction, the card shows nothing (no fallback to storyline title or story_type badge).

### System
- `GET /health` - Health check
- `GET /config` - Get system configuration status

## Frontend-Backend Integration

> **⚠️ TODO / PLANNED: This section is planned and may not be fully implemented yet.**

The frontend React application communicates with the FastAPI backend through REST API endpoints:

### Data Flow

1. **Dashboard**: Fetches NASDAQ 100 stock list from `/stocks/nasdaq100` API
2. **Stock Selection**: User selects a stock from Portfolio/Watchlist
3. **Stock Detail Page**: 
   - **Stock Tab**: Fetches news from `/news/stock?ticker=XXX&start_date=...&end_date=...` API
   - **Macro Tab**: Fetches macro news from `/news/macro?ticker=XXX&start_date=...&end_date=...` API
   - **Storyline Tab**: Fetches storylines from `/storylines?ticker=XXX` API
4. **News Detail**: Clicking a news item opens detail overlay showing:
   - Title, published date, source, URL, summary
   - For Macro news: primary topic and related tickers
   - AI Insight and Sentiment Analysis (placeholders for future implementation)
   - User comments (stored in browser localStorage)

### Time Range Filtering

The frontend supports time range filtering with the following options:
- 1D (1 day)
- 1W (1 week) - **Default**
- 1M (1 month)
- 3M (3 months)
- 6M (6 months)
- 1Y (1 year)
- Customized (user-defined date range)

Time ranges are calculated on the frontend and passed to the backend API as `start_date` and `end_date` parameters.

### User Comments

User comments are stored in browser localStorage with the key format: `news_comment_{newsId}`. Comments persist across page refreshes but are local to each browser.

## Project Structure

```
Morning_Edge/
├── backend/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Configuration settings
│   ├── models.py               # Pydantic data models
│   ├── services/
│   │   ├── collectors/         # Data source collectors
│   │   │   ├── base.py         # BaseCollector abstract class
│   │   │   ├── rss_collector.py # RSSCollector base class
│   │   │   ├── alpha_vantage.py
│   │   │   ├── sec_edgar.py
│   │   │   ├── nasdaq_rss.py
│   │   │   ├── fred.py
│   │   │   ├── financial_datasets.py
│   │   │   ├── newsnow.py
│   │   │   ├── massive.py
│   │   │   ├── marketaux.py
│   │   │   ├── openai.py
│   │   │   ├── gemini.py
│   │   │   ├── news_registry.py # News source registry
│   │   │   └── mock_data.py    # Mock data + placeholder pseudocode
│   │   ├── news_filters/        # News filtering system
│   │   │   ├── base.py         # NewsFilter base class
│   │   │   ├── filter_factory.py # Filter factory
│   │   │   ├── keyword_filter.py
│   │   │   ├── openai_filter.py
│   │   │   └── gemini_filter.py
│   │   ├── filters.py          # Data filtering & deduplication
│   │   ├── news_aggregator.py  # Multi-source news aggregation
│   │   ├── tagging.py          # Impact scoring & categorization
│   │   ├── briefing.py         # Report generation
│   │   └── ai_summaries.py     # OpenAI/Gemini integration
│   ├── pipeline/                # News Storyline Pipeline
│   │   ├── pipeline.py          # Main pipeline orchestrator
│   │   ├── news_collection.py   # Collect & store news with embeddings
│   │   ├── rag_retrieval.py     # Similar-article retrieval (RAG)
│   │   ├── relationship_classifier.py  # LLM relationship classification
│   │   └── storyline_manager.py # Create/update storylines, link articles
│   ├── scripts/                 # Backfill & maintenance scripts
│   │   ├── backfill_embeddings.py
│   │   ├── remove_long_storylines.py
│   │   └── remove_duplicate_news_articles.py
│   └── storage/
│       ├── supabase_client.py  # Supabase connection
│       ├── stocks_save.py       # Save stocks to database
│       ├── stocks_query.py      # Query stocks from database
│       ├── stocks_main.py       # Main function for stocks operations
│       ├── news_articles_save.py # Save news articles to database
│       ├── news_articles_query.py # Query news articles from database
│       ├── news_articles_main.py  # Main function for news operations
│       ├── news_articles_daily.py # Daily news update (recent/overnight)
│       ├── embedding_utils.py   # OpenAI summary embeddings
│       ├── news_collectors.py     # External API news collectors
│       ├── nasdaq100_tickers.py   # NASDAQ 100 ticker list
│       ├── watchlist_manager.py
│       └── watchlist.json         # Persisted watchlist
├── frontend/                    # Frontend application (React + TypeScript + Vite)
│   ├── components/
│   │   ├── Dashboard.tsx
│   │   ├── Login.tsx
│   │   ├── StockCard.tsx
│   │   └── StockDetail.tsx      # Stock detail: Storyline tab, supporting articles (timeline, URL, summary toggle, relation badge)
│   ├── App.tsx                  # Main React app
│   ├── index.tsx                # Entry point
│   ├── types.ts                 # TypeScript type definitions
│   ├── vite.config.ts           # Vite configuration
│   └── package.json
├── data/                       # Data storage directory
├── .env                        # Environment variables (not in git)
├── .env.example                # Example environment variables
├── requirements.txt            # Python dependencies
└── README.md
```

## Trading Direction Algorithm

The system uses a weighted heuristic approach to determine trading direction:

| Signal Type | Weight | Description |
|------------|--------|-------------|
| News Sentiment | 25% | Keyword-based positive/negative analysis |
| Technical | 30% | Price change, support/resistance levels |
| Market Sentiment | 20% | Social media sentiment scores |
| SEC Filings | 15% | Filing type impact analysis |
| Macro Events | 10% | Economic event influence |

**Direction thresholds**:
- Score > 0.15: BUY
- Score < -0.15: SELL
- Otherwise: HOLD

## Storage Module Structure

The storage module follows a clean separation of concerns:

### Stocks Operations
- **`stocks_save.py`**: Save/update stocks in database
- **`stocks_query.py`**: Query stocks from database
- **`stocks_main.py`**: Main script to populate stocks table

### News Articles Operations
- **`news_articles_save.py`**: Save news articles to database
- **`news_articles_query.py`**: Query news articles from database
- **`news_articles_main.py`**: Main script to fetch and store news

### External API Collectors
- **`news_collectors.py`**: Fetch news from external APIs (Financial Datasets, Alpha Vantage, Massive, Marketaux)

### NASDAQ 100 Ticker Management
- **`nasdaq100_tickers.py`**: Fetches NASDAQ 100 ticker list with company information
  - Supports FMP API (requires `FMP_API_KEY`)
  - Includes hardcoded fallback list of top 100 NASDAQ stocks
  - Provides ticker, company name, and exchange information

### Running Storage Scripts

#### Populate Stocks Table

Run once or when updating the stock list:

```bash
python backend/storage/stocks_main.py
```

#### Fetch and Store News Articles

The `news_articles_main.py` script fetches news articles from Alpha Vantage and Massive APIs for all stocks in your database. It processes news in 15-day date buckets to respect API limits.

**Command Line Usage**:

```bash
# Use default date range (last 5 days ending yesterday)
python backend/storage/news_articles_main.py

# Fetch news from a specific start date to yesterday
python backend/storage/news_articles_main.py --start-date 2026-01-20

# Fetch news for last 5 days ending on a specific date
python backend/storage/news_articles_main.py --end-date 2026-01-24

# Fetch news for a specific date range
python backend/storage/news_articles_main.py --start-date 2026-01-20 --end-date 2026-01-24
```

**Date Format**: `YYYY-MM-DD` (e.g., `2026-01-20`)

**VS Code Debug Configuration**:

The project includes a VS Code launch configuration for debugging `news_articles_main.py`. To use it:

1. Open VS Code in the project root
2. Go to Run and Debug (F5 or Cmd+Shift+D)
3. Select "Test: News Articles Main" from the dropdown
4. Click Run (F5) or set breakpoints and click Debug

The launch configuration is defined in `.vscode/launch.json`:

```json
{
    "name": "Test: News Articles Main",
    "type": "debugpy",
    "request": "launch",
    "program": "${workspaceFolder}/backend/storage/news_articles_main.py",
    "args": ["--start-date", "2025-11-19", "--end-date", "2026-01-25"],
    "cwd": "${workspaceFolder}",
    "console": "integratedTerminal",
    "justMyCode": true,
    "env": {
        "PYTHONPATH": "${workspaceFolder}"
    },
    "envFile": "${workspaceFolder}/.env"
}
```

You can modify the `args` array in the launch configuration to change the date range, or pass arguments when running from the command line.

**What the Script Does**:

1. Connects to Supabase database
2. Fetches all stocks from the database
3. For each stock, fetches news from:
   - Alpha Vantage API (15-day buckets)
   - Massive API (15-day buckets)
4. Filters news for relevance using OpenAI filter (with keyword fallback)
5. Removes duplicate titles using embedding-based similarity
6. Saves filtered news articles to the `news_articles` table
7. Logs progress and summary statistics

**Logs**: The script logs to both console and `logs/news_articles.log` with rotation (max 10MB per file, keeps 5 backups).

**Daily Update**: For automated daily updates, see the [Daily News Update](#daily-news-update) section below.

### News Storyline Pipeline

The **News Storyline Pipeline** (`backend/pipeline/`) turns recent and overnight news into storylines: it collects news, embeds summaries, retrieves similar past articles, classifies relationships, and creates or updates storylines with LLM-generated themes and summaries.

**Flow**: News → Embed → Retrieve → Reason → Attach → Summarize → Evolve

1. **Collect** – Uses OpenAI collector (with web search) to get recent/overnight news per ticker; no date range in the prompt (always “recent and overnight”).
2. **Store** – Saves articles to `news_articles` with summary embeddings (OpenAI `text-embedding-3-small`).
3. **Retrieve** – RAG: fetches top-K similar historical articles by embedding similarity (cursor-based pagination for backfill).
4. **Classify** – LLM classifies each (new article, similar article) as CONTINUATION, ESCALATION, CONTRADICTION, RESOLUTION, NEW_ANGLE, or UNRELATED.
5. **Decide** – Picks storyline by recency, then relationship strength (ESCALATION > CONTINUATION > NEW_ANGLE), then similarity.
6. **Create or reuse** – If no match: creates a new storyline with a single LLM call that returns both the summary and which historical article IDs were used; those articles are linked with relation type CONTEXT. Storyline IDs are generated like news articles: string ID `storyline_{12_char_hash}` from ticker + normalized theme + first article ID, then converted to bigint.
7. **Link** – Writes to `long_story_article_links`. article_ticker is the linked article’s ticker; storyline_ticker is the storyline’s main ticker. New article is linked with its classified relation type; historical articles used in the summary are linked with CONTEXT.
8. **Evolve** – For existing storylines, updates the storyline summary with the new article (only when not UNRELATED).

**Run manually**:

```bash
python -m backend.pipeline.pipeline
```

**Backfill embeddings** (for existing articles without embeddings):

```bash
python -m backend.storage.backfill_embeddings
# Optional: --batch-size 1000 --update-concurrency 50
```

Embeddings use OpenAI `text-embedding-3-small` (1536-dim). To re-embed all rows with the current model (e.g. after a dimension change), run the migration `backend/scripts/migrations/embedding_1536_openai.sql` first (drops and recreates `embedding vector(1536)` on `news_articles`, `macro_articles`, `sec_filing_chunks`), then run `python -m backend.scripts.backfill_embeddings_new_model`. See `backend/scripts/BACKFILL_EMBEDDINGS_NEW_MODEL_README.md`.

**Database tables**:
- `long_stories` and `long_story_article_links` – used for the Long Story / Current News experience.

**MorningEdge integration**:
- The **Storyline** / **Long Story** tab (category Stock) uses `GET /stories` and `GET /long-stories` for the selected ticker. Clicking a story opens a detail overlay.
- **Supporting articles** are loaded from `GET /storylines/{id}/articles`. The overlay shows them in a **timeline** (timestamp on the left), with **clickable titles** (open article URL), a **chevron** to expand/collapse the article summary, and a **relationship badge** on the right (e.g. CONTEXT, NEW_ANGLE, CONTINUATION from `relation_type`).
- Storyline and article IDs are passed as **strings** end-to-end so large bigint IDs are not truncated by JavaScript.

## Customization

### Adding New Keywords

Edit `backend/config.py`:
```python
DEFAULT_KEYWORDS = [
    "earnings", "revenue", "your_keyword_here",
    # ...
]
```

### Adjusting Impact Levels

Edit `backend/config.py`:
```python
HIGH_IMPACT_KEYWORDS = ["earnings", "your_high_impact_keyword"]
MEDIUM_IMPACT_KEYWORDS = ["dividend", "your_medium_impact_keyword"]
```

### Adjusting Relevance Threshold

Edit `backend/config.py`:
```python
RELEVANCE_THRESHOLD = 0.1  # Default: 0.1 (lowered from 0.3 to avoid over-filtering)
```

Lower values (e.g., 0.1) allow more news items through, while higher values (e.g., 0.3) filter more aggressively.

### Configuring News Sources

Edit `NEWS_SOURCES` in `backend/config.py` to enable/disable sources or adjust priorities:
```python
NEWS_SOURCES = {
    "nasdaq_rss": {
        "enabled": True,
        "priority": 1,  # Lower = higher priority
        "max_items_per_symbol": 20,
        "freshness_days": 3,
        "reliability_score": 0.8
    },
    # ... other sources
}
```

### Adding New Data Sources

1. **Create a new collector** in `backend/services/collectors/`
   - For RSS sources: Inherit from `RSSCollector`
   - For API sources: Inherit from `BaseCollector`
   - Implement the `collect()` or `collect_news()` method
   - Set appropriate `source_type` ("news", "technical", "macro", or "multi")

2. **Register the collector**:
   - Initialize in `BriefingGenerator.__init__()`
   - Register in `BriefingGenerator._register_collectors()`
   - Export in `backend/services/collectors/__init__.py`

3. **Add configuration** to `NEWS_SOURCES` in `backend/config.py`:
   ```python
   "your_collector": {
       "enabled": True,
       "priority": 5,  # Lower = higher priority
       "max_items_per_symbol": 50,
       "freshness_days": 3,
       "reliability_score": 0.7,
       "name": "Your Collector",
       "source_type": "news"
   }
   ```

4. **Add API key** (if required) to `.env` and `config.py`

### Adding New News Filters

1. Create a new filter class in `backend/services/news_filters/`
2. Inherit from `NewsFilter` base class
3. Implement `filter()` method
4. Register in `FilterFactory.create_filter()`

## Development

### Debugging

The project includes VS Code launch configurations in `.vscode/launch.json`:

- **Python: Current File**: Run/debug the currently open Python file
- **Debug: debug_storage.py**: Debug storage operations
- **Test: Simple Connection**: Test database connection
- **Test: News Collectors**: Test news collectors with arguments
- **Test: News Articles Main**: Debug news articles script with date range arguments

To use a launch configuration:
1. Open the Run and Debug panel (F5 or Cmd+Shift+D)
2. Select the configuration from the dropdown
3. Set breakpoints in your code
4. Click Run (F5) or Debug (F5)

You can modify the `args` array in `.vscode/launch.json` to change command-line arguments for each configuration.

### Storage Module Architecture

The storage module uses Supabase Python client for all database operations:
- **Connection**: `supabase_client.py` manages Supabase client instance
- **Separation**: Each table has separate save and query modules
- **Main Functions**: Each table has its own main script for data operations
- **Watchlist Management**: `watchlist_manager.py` handles watchlist persistence (JSON file or database)

### News Collection Architecture

The system follows a multi-layered collection strategy:

1. **Direct Collection**: Fast sources collected directly with specific timeouts
   - Nasdaq RSS: 10s timeout
   - Financial Datasets: 15s timeout
   - NewsNow: 60s timeout (queries multiple platforms)

2. **Aggregator Collection**: Additional sources via NewsAggregator
   - Parallel execution with per-collector timeouts (30s default)
   - Global timeout cap (40s) to prevent hanging
   - Graceful error handling

3. **Filtering Pipeline**:
   - Time window filtering
   - Relevance scoring
   - Financial news classification (AI or keyword-based)
   - Language-aware deduplication

4. **Processing**:
   - Impact and category tagging
   - Sorting by impact and relevance
   - Conversion of NewsNow items to MacroEvents

## Architecture Highlights

### Collector Pattern

The system uses a flexible collector pattern:
- **BaseCollector**: Abstract base class for all collectors
- **RSSCollector**: Base class for RSS-based news sources with built-in feed parsing
- **Source Types**: "news", "technical", "macro", or "multi"
- **Availability Tracking**: Collectors mark themselves unavailable on errors

### News Aggregation Flow

```
1. BriefingGenerator.generate()
   ↓
2. Direct Collection (fast sources: Nasdaq RSS, Financial Datasets, NewsNow)
   ↓
3. NewsAggregator (additional sources in parallel)
   ↓
4. Aggregate all news items
   ↓
5. Separate NewsNow → MacroEvents, Others → News
   ↓
6. DataFilter.filter_news() (relevance filtering)
   ↓
7. Impact/Category tagging
   ↓
8. Sort by impact
   ↓
9. Return BriefingReport
```

### Filtering Strategy

1. **Time Window Filter**: Filters items by publication date
2. **Relevance Filter**: Scores items by symbol mentions and keywords
3. **Financial News Filter**: AI-based classification (OpenAI/Gemini) with keyword fallback
4. **Language-Aware Deduplication**: Prevents duplicate removal across languages

## Daily News Update

The system includes an automated daily news update that runs via GitHub Actions to fetch news for yesterday (day T) when executed at 5am T+1.

### Automated Daily Updates

A GitHub Actions workflow (`.github/workflows/daily_news_update.yml`) automatically runs `news_articles_daily.py` daily at 5am UTC to fetch news from the previous day.

**Setup**:
1. Ensure all required secrets are configured in GitHub (Settings → Secrets and variables → Actions):
   - `SUPABASE_URL`
   - `DB_API_KEY` or `SUPABASE_KEY`
   - `OPENAI_API_KEY`
   - `ALPHA_VANTAGE_API_KEY`
   - `MASSIVE_API_KEY`
   - Other API keys as needed

2. The workflow runs automatically once the file is committed to the repository

3. You can manually trigger it from the GitHub Actions tab

**Manual Daily Update**:

You can also run the daily update script manually:

```bash
# Fetch news for yesterday (default)
python backend/storage/news_articles_daily.py
```

The daily update script:
- Fetches news for a single day (yesterday by default)
- Processes all stocks in the database
- Uses the same filtering and deduplication as the main script
- Logs to `logs/news_articles_daily.log`

### Daily Macro News Update

A GitHub Actions workflow (`.github/workflows/daily_macro_news_update.yml`) automatically runs `macro_articles_daily.py` daily at 5am UTC to fetch macro news from the previous day. It:

1. Fetches macro economic news from Alpha Vantage NEWS_SENTIMENT API for topics: economy_fiscal, economy_monetary, economy_macro
2. Filters articles by relevance (only keeps articles where macro topics have relevance_score > 0.9)
3. Deduplicates similar articles based on title and summary similarity
4. Creates embeddings (OpenAI text-embedding-3-small) for article summaries
5. Stores articles in the `macro_articles` table

**Setup**: Requires the same secrets as daily news update, plus `ALPHA_VANTAGE_API_KEY`. You can also trigger this workflow manually from the Actions tab.

**Manual Macro News Update**:

You can also run the daily macro news update script manually:

```bash
# Fetch macro news for yesterday (default)
python backend/storage/macro_articles_daily.py
```

The daily macro news update script:
- Fetches macro news for a single day (yesterday by default)
- Uses the same date range logic as daily news update (00:00:00 to 23:59:59 UTC for the target day)
- Logs to console (visible in GitHub Actions)

### Daily Pipeline

A GitHub Actions workflow (`.github/workflows/daily_pipeline.yml`) runs the **legacy** News Storyline Pipeline daily at 12pm UTC (after the 5am daily news updates). It runs `python -m backend.pipeline.pipeline` (Task 1 collect+store, Task 2 per-article storylines). The **current** recommended story pipeline is the **overnight pipeline** (`python -m backend.pipeline.overnight_pipeline.runner`); see `backend/pipeline/overnight_pipeline/README.md`. To run that on a schedule, add a job that invokes the overnight runner with the desired `--asof-date`.

**Secrets**: Same as daily news update (including `OPENAI_API_KEY`). You can trigger the workflow manually from the Actions tab.

## Limitations

- Alpha Vantage free tier: 25 API calls per day
- SEC EDGAR rate limit: 10 requests per second
- Financial Datasets API: Rate limits apply (check your plan)
- Massive API: Rate limits apply (check your plan)
- Marketaux API: Rate limits apply (check your plan)
- OpenAI API: Rate limits and costs apply (check your plan)
- Gemini API: Rate limits apply (check your plan)
- Real-time prices may have 15-minute delay on free tiers
- Social sentiment currently uses mock data (real APIs require paid subscriptions)
- NewsNow API: Free but may have rate limits

## License

MIT License
