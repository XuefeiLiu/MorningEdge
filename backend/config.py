"""
Configuration settings for the Morning Edge pre-market briefing system.
"""
import os
from datetime import datetime, time
from typing import Optional, Dict, List
from dotenv import load_dotenv

load_dotenv()

# API Keys
ALPHA_VANTAGE_API_KEY: Optional[str] = os.getenv("ALPHA_VANTAGE_API_KEY")
OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")

# Alpaca API Keys (for real-time market data)
# Note: env vars use hyphens per user's .env format
_alpaca_key = os.getenv("alpaca-api-key", "").strip().strip("'\"")
_alpaca_secret = os.getenv("alpaca-secret-key", "").strip().strip("'\"")
ALPACA_API_KEY: Optional[str] = _alpaca_key or None
ALPACA_SECRET_KEY: Optional[str] = _alpaca_secret or None

# Data Source URLs
SEC_EDGAR_BASE_URL = "https://data.sec.gov"
NASDAQ_RSS_BASE_URL = "https://www.nasdaq.com/feed/rssoutbound"
FRED_API_BASE_URL = "https://api.stlouisfed.org/fred"
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"

# Market Hours (US Eastern Time)
MARKET_OPEN_TIME = time(9, 30)  # 9:30 AM ET
MARKET_CLOSE_TIME = time(16, 0)  # 4:00 PM ET

# Filtering Settings
DEFAULT_KEYWORDS = [
    "earnings", "revenue", "profit", "loss", "guidance", "forecast",
    "acquisition", "merger", "dividend", "buyback", "layoff", "restructuring",
    "FDA", "approval", "patent", "lawsuit", "settlement", "investigation",
    "upgrade", "downgrade", "rating", "target", "analyst", "outlook",
    "inflation", "interest rate", "fed", "gdp", "unemployment", "jobs"
]

# Impact Scoring Thresholds
HIGH_IMPACT_KEYWORDS = [
    "earnings", "acquisition", "merger", "FDA approval", "bankruptcy",
    "investigation", "lawsuit", "guidance", "forecast", "rate decision"
]
MEDIUM_IMPACT_KEYWORDS = [
    "dividend", "buyback", "upgrade", "downgrade", "analyst",
    "partnership", "contract", "expansion"
]

# Relevance score threshold (0-1)
RELEVANCE_THRESHOLD = 0.3

# Duplicate detection similarity threshold
DUPLICATE_SIMILARITY_THRESHOLD = 0.85

# Embedding: OpenAI text-embedding-3-small (1536-dim, matches DB vector(1536))
EMBEDDING_DIMENSION = 1536  # Must match DB vector(1536). text-embedding-3-small outputs 1536
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_TIMEOUT = float(os.getenv("EMBEDDING_TIMEOUT", "90"))  # Request timeout for OpenAI embeddings

# Data collection settings
MAX_NEWS_ITEMS_PER_SOURCE = 50
MAX_FILINGS_PER_STOCK = 10

# Storage paths
WATCHLIST_FILE = "backend/storage/watchlist.json"
DATA_DIR = "data"

# OpenAI Settings
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # Can be overridden with OPENAI_MODEL env var (e.g., "gpt-5.2")
OPENAI_MAX_TOKENS = 2000
OPENAI_FILTER_BATCH_SIZE = int(os.getenv("OPENAI_FILTER_BATCH_SIZE", "10"))
OPENAI_FILTER_MAX_CONCURRENT_BATCHES = int(os.getenv("OPENAI_FILTER_MAX_CONCURRENT_BATCHES", "15"))

# Gemini Settings
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-pro-preview")
GEMINI_MAX_TOKENS = 2000

# Financial Datasets API
FINANCIAL_DATASETS_API_KEY: Optional[str] = os.getenv("FINANCIAL_DATASETS_API_KEY")
FINANCIAL_DATASETS_API_URL = "https://api.financialdatasets.ai/news/"

# Massive API
MASSIVE_API_KEY: Optional[str] = os.getenv("MASSIVE_API_KEY")
MASSIVE_API_URL = "https://api.massive.com/v2/reference/news"

# Marketaux API
MARKETAUX_API_KEY: Optional[str] = os.getenv("MARKETAUX_API_KEY")
MARKETAUX_API_URL = "https://api.marketaux.com/v1/news/all"

# NewsNow API Configuration
NEWSNOW_API_URL = "https://newsnow.busiyi.world/api/s"
NEWSNOW_REQUEST_INTERVAL_MS = 2000
NEWSNOW_MAX_RETRIES = 2

# News Source Configuration
NEWS_SOURCES = {
    "nasdaq_rss": {
        "enabled": True,
        "priority": 1,
        "max_items_per_symbol": 20,
        "freshness_days": 3,
        "reliability_score": 0.8,
        "name": "Nasdaq RSS",
        "source_type": "news"
    },
    "alpha_vantage": {
        "enabled": True,
        "priority": 2,
        "max_items_per_symbol": 50,
        "requires_api_key": True,
        "reliability_score": 0.7,
        "name": "Alpha Vantage",
        "source_type": "multi"
    },
    "newsnow": {
        "enabled": True,
        "priority": 3,
        "api_url": NEWSNOW_API_URL,
        "request_interval_ms": NEWSNOW_REQUEST_INTERVAL_MS,
        "max_retries": NEWSNOW_MAX_RETRIES,
        "reliability_score": 0.6,
        "name": "NewsNow",
        "source_type": "news",
        "platforms": {
            "toutiao": {"enabled": True, "name": "今日头条"},
            "wallstreetcn-hot": {"enabled": True, "name": "华尔街见闻"},
            "thepaper": {"enabled": True, "name": "澎湃新闻"},
            "cls-hot": {"enabled": True, "name": "财联社热门"},
        }
    },
    "financial_datasets": {
        "enabled": bool(FINANCIAL_DATASETS_API_KEY),
        "priority": 4,
        "api_url": FINANCIAL_DATASETS_API_URL,
        "requires_api_key": True,
        "max_items_per_symbol": 100,
        "cache_enabled": True,
        "rate_limit_backoff": [60, 90, 120, 150],
        "reliability_score": 0.8,
        "name": "Financial Datasets",
        "source_type": "news"
    }
}

# News Aggregation Settings
NEWS_AGGREGATION = {
    "deduplication_threshold": 0.85,
    "max_items_per_source": 50,
    "global_timeout": 60.0
}


# Pipeline Configuration
PIPELINE_RUN_TIME = "07:00"  # 7am default
# RAG: retrieve top K candidates then rerank to N by mode (local cross-encoder, free)
RAG_TOP_K_CANDIDATES = int(os.getenv("RAG_TOP_K_CANDIDATES", "50"))  # Broad retrieval before rerank
RAG_RETRIEVAL_LIMIT = int(os.getenv("RAG_RETRIEVAL_LIMIT", "6"))  # Legacy; pipeline uses RAG_TOP_K_CANDIDATES + rerank
RAG_RERANK_TOP_N_RECENT_MIN = int(os.getenv("RAG_RERANK_TOP_N_RECENT_MIN", "3"))
RAG_RERANK_TOP_N_RECENT_MAX = int(os.getenv("RAG_RERANK_TOP_N_RECENT_MAX", "8"))
RAG_RERANK_TOP_N_HISTORY = int(os.getenv("RAG_RERANK_TOP_N_HISTORY", "20"))
# Long story: retrieval window (days). Default 5 years so long narrative can use past 5 years of articles.
LONG_STORY_DAYS = int(os.getenv("LONG_STORY_DAYS", str(365 * 5)))
# Long story cutoff: minimum useful articles (after LLM filter) required to create a long storyline. Not created if below this.
MIN_LONG_STORY_ARTICLES = int(os.getenv("MIN_LONG_STORY_ARTICLES", "4"))
MAX_LONG_STORY_ARTICLES = int(os.getenv("MAX_LONG_STORY_ARTICLES", "30"))
LONG_STORY_SIMILARITY_THRESHOLD = float(os.getenv("LONG_STORY_SIMILARITY_THRESHOLD", "0.8"))
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")  # Local, free
PIPELINE_TICKER_CONCURRENCY = int(os.getenv("PIPELINE_TICKER_CONCURRENCY", "4"))  # Max tickers processed in parallel
PIPELINE_ARTICLE_CONCURRENCY = int(os.getenv("PIPELINE_ARTICLE_CONCURRENCY", "3"))  # Max articles per ticker processed in parallel
# Gemini-generated articles: do not save to news_articles and do not create long stories.
# Judge by the source returned by get_stock_news_prompt: when the model returns this exact source, treat as Gemini-generated.
GEMINI_GENERATED_SOURCE = "Gemini Generated"
# OpenAI-generated marker (from OpenAI collector); excluded from RAG similar-article retrieval.
OPENAI_GENERATED_SOURCE = "OpenAI Generated"
# RAG: do not use articles with these sources when retrieving similar articles (AI-generated summaries).
RAG_EXCLUDED_SOURCES: List[str] = [GEMINI_GENERATED_SOURCE, OPENAI_GENERATED_SOURCE]


def is_gemini_generated(collector: str = None, source: str = None) -> bool:
    """True if the article source is the Gemini-generated marker (source returned by get_stock_news_prompt). Such articles are not saved to news_articles and get no long story."""
    return (source or "").strip() == GEMINI_GENERATED_SOURCE
# User-created story (UI chatbot): max query length
CUSTOM_STORY_QUERY_MAX_CHARS = int(os.getenv("CUSTOM_STORY_QUERY_MAX_CHARS", "200"))
# Ask/custom story: token and context caps (limit OpenAI usage)
CUSTOM_STORY_MAX_TOKENS = int(os.getenv("CUSTOM_STORY_MAX_TOKENS", "800"))
CUSTOM_STORY_CONTEXT_ARTICLES = int(os.getenv("CUSTOM_STORY_CONTEXT_ARTICLES", "12"))
CUSTOM_STORY_ARTICLE_SUMMARY_CHARS = int(os.getenv("CUSTOM_STORY_ARTICLE_SUMMARY_CHARS", "300"))
# Ask: rate limit (requests per window per IP)
ASK_RATE_LIMIT_PER_MINUTE = int(os.getenv("ASK_RATE_LIMIT_PER_MINUTE", "10"))
ASK_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("ASK_RATE_LIMIT_WINDOW_SECONDS", "60"))
# Ask: daily quota per IP = max questions per user per day (0 = disabled). Default 3 rounds per day.
ASK_DAILY_QUOTA_PER_IP = int(os.getenv("ASK_DAILY_QUOTA_PER_IP", "3"))
# Ask: max concurrent requests (0 = unlimited)
ASK_MAX_CONCURRENT = int(os.getenv("ASK_MAX_CONCURRENT", "0"))

# Related tickers (competitors, suppliers, customers) for RAG multi-ticker retrieval.
# Source of truth is stocks.related_tickers in the DB (populated by backend/storage/build_related_tickers.py).
# Fallback when DB is not available (e.g. in tests); normally empty.
RELATED_TICKERS: Dict[str, List[str]] = {}

# 10-K/10-Q filings RAG and filing-in-storyline
FILING_BACKFILL_DAYS = int(os.getenv("FILING_BACKFILL_DAYS", str(365 * 4)))
FILING_UPDATE_DAYS = int(os.getenv("FILING_UPDATE_DAYS", "1"))
FILING_CHUNK_SIZE = int(os.getenv("FILING_CHUNK_SIZE", "1000"))
FILING_CHUNK_OVERLAP = int(os.getenv("FILING_CHUNK_OVERLAP", "150"))
# Token-based chunking (plan: 300-700 tokens, 10-15% overlap)
FILING_CHUNK_MAX_TOKENS = int(os.getenv("FILING_CHUNK_MAX_TOKENS", "600"))
FILING_CHUNK_OVERLAP_RATIO = float(os.getenv("FILING_CHUNK_OVERLAP_RATIO", "0.12"))
SEC_FETCH_TIMEOUT = float(os.getenv("SEC_FETCH_TIMEOUT", "60.0"))
SEC_RATE_LIMIT_DELAY = float(os.getenv("SEC_RATE_LIMIT_DELAY", "1.0"))  # seconds between SEC requests (stay under 10 req/s; 1.0 = 1 req/s)
SEC_429_BACKOFF_SECONDS = int(os.getenv("SEC_429_BACKOFF_SECONDS", "60"))  # wait and retry on 429
# How many of the "recent" filings list to scan per company (SEC returns up to ~1000; higher = older filings e.g. 2022)
SEC_FILINGS_RECENT_LIMIT = int(os.getenv("SEC_FILINGS_RECENT_LIMIT", "500"))
FILING_FORMS = ("10-K", "10-Q")
PIPELINE_RUN_FILING_UPDATE = os.getenv("PIPELINE_RUN_FILING_UPDATE", "false").strip().lower() in ("true", "1", "yes")
# RAG filing retrieval: hybrid score weights (similarity + recency + doc-type priority)
RAG_FILING_SIMILARITY_WEIGHT = float(os.getenv("RAG_FILING_SIMILARITY_WEIGHT", "0.6"))
RAG_FILING_RECENCY_WEIGHT = float(os.getenv("RAG_FILING_RECENCY_WEIGHT", "0.3"))
RAG_FILING_DOC_PRIORITY_WEIGHT = float(os.getenv("RAG_FILING_DOC_PRIORITY_WEIGHT", "0.1"))

# Macro digest (daily analyst reports, KB RAG, impact)
PIPELINE_RUN_MACRO_DIGEST = os.getenv("PIPELINE_RUN_MACRO_DIGEST", "true").strip().lower() in ("true", "1", "yes")
MACRO_KB_PDF_PATH = os.getenv("MACRO_KB_PDF_PATH", "MacroEcon")  # folder or path to PDF(s)
MACRO_TOPICS: List[str] = [
    "FX",
    "RATE",
    "CREDIT",
    "COMMODITY",
    "EQUITY",
    "Fiscal Policy",
    "Monetary Policy",
    "Trump",
]
MACRO_KB_CHUNK_MAX_TOKENS = int(os.getenv("MACRO_KB_CHUNK_MAX_TOKENS", "1000"))
MACRO_KB_CHUNK_OVERLAP_RATIO = float(os.getenv("MACRO_KB_CHUNK_OVERLAP_RATIO", "0.15"))
MACRO_KB_CHUNK_HARD_MAX_TOKENS = int(os.getenv("MACRO_KB_CHUNK_HARD_MAX_TOKENS", "1500"))
MACRO_KB_RETRIEVAL_TOP_K = int(os.getenv("MACRO_KB_RETRIEVAL_TOP_K", "20"))
MACRO_KB_RERANK_TOP_K = int(os.getenv("MACRO_KB_RERANK_TOP_K", "8"))
# KB chunks per topic for brief synthesis (retrieve then keep top N). 0 = disable KB in briefs.
MACRO_KB_BRIEF_TOP_K = int(os.getenv("MACRO_KB_BRIEF_TOP_K", "8"))
# Min relevance_score (0-100) for raw items passed to synthesis; 0 = no filter. Raise to drop noisy/low-signal items
MACRO_RAW_MIN_RELEVANCE = int(os.getenv("MACRO_RAW_MIN_RELEVANCE", "50"))
