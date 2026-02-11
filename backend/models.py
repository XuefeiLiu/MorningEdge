"""
Pydantic models for requests and responses.
"""
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ImpactLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(str, Enum):
    COMPANY_NEWS = "company_news"
    MACRO_EVENT = "macro_event"
    TECHNICAL_DATA = "technical_data"
    MARKET_SENTIMENT = "market_sentiment"


class TradingDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


# Request Models
class WatchlistUpdateRequest(BaseModel):
    symbols: List[str] = Field(..., description="List of stock ticker symbols")


class TimeWindowRequest(BaseModel):
    start_time: Optional[datetime] = Field(None, description="Start of data collection window")
    end_time: Optional[datetime] = Field(None, description="End of data collection window")


class FilterSettingsRequest(BaseModel):
    keywords: Optional[List[str]] = Field(None, description="Custom filter keywords")
    relevance_threshold: Optional[float] = Field(None, ge=0, le=1, description="Relevance score threshold")
    impact_priority: Optional[List[ImpactLevel]] = Field(None, description="Impact levels to include")


# Data Models
class NewsItem(BaseModel):
    id: str
    ticker: str
    published_at: datetime
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    collector: str
    embedding: Optional[List[float]] = None  # Vector embedding for the summary (not title)


class MacroEvent(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    source: str
    event_time: datetime
    indicator: Optional[str] = None
    actual_value: Optional[str] = None
    expected_value: Optional[str] = None
    previous_value: Optional[str] = None
    impact_level: ImpactLevel = ImpactLevel.LOW


class TechnicalData(BaseModel):
    symbol: str
    timestamp: datetime
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    volume: Optional[int] = None
    previous_close: Optional[float] = None
    change_percent: Optional[float] = None
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    volatility: Optional[float] = None


class SentimentData(BaseModel):
    symbol: Optional[str] = None
    source: str
    timestamp: datetime
    sentiment_score: float = Field(ge=-1, le=1, description="Sentiment from -1 (bearish) to 1 (bullish)")
    volume: Optional[int] = Field(None, description="Number of mentions/discussions")
    trending_topics: List[str] = Field(default_factory=list)


class SECFiling(BaseModel):
    id: str
    symbol: str
    form_type: str
    filed_date: datetime
    description: Optional[str] = None
    url: str
    impact_level: ImpactLevel = ImpactLevel.LOW
    accession_number: Optional[str] = None  # SEC accession (e.g. 0000320193-24-000123) for filings backfill


# Stock Summary Models
class StockImpactSummary(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    trading_direction: TradingDirection = TradingDirection.HOLD
    confidence_score: float = Field(ge=0, le=1, default=0.5)
    key_drivers: List[str] = Field(default_factory=list)
    news_count: int = 0
    filings_count: int = 0
    sentiment_score: Optional[float] = None
    technical_summary: Optional[TechnicalData] = None
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    risk_warnings: List[str] = Field(default_factory=list)
    ai_summary: Optional[str] = None


# Response Models
class WatchlistResponse(BaseModel):
    symbols: List[str]
    updated_at: datetime


class BriefingReport(BaseModel):
    generated_at: datetime
    time_window_start: datetime
    time_window_end: datetime
    watchlist: List[str]
    
    # Categorized data streams
    company_news: List[NewsItem] = Field(default_factory=list)
    macro_events: List[MacroEvent] = Field(default_factory=list)
    technical_data: List[TechnicalData] = Field(default_factory=list)
    market_sentiment: List[SentimentData] = Field(default_factory=list)
    sec_filings: List[SECFiling] = Field(default_factory=list)
    
    # Per-stock summaries
    stock_summaries: List[StockImpactSummary] = Field(default_factory=list)
    
    # Overall market summary
    market_overview: Optional[str] = None
    high_impact_items_count: int = 0
    risk_warnings: List[str] = Field(default_factory=list)


class AISummaryRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(..., description="Items to summarize")
    focus_symbols: Optional[List[str]] = Field(None, description="Symbols to focus on")


class AISummaryResponse(BaseModel):
    summary: str
    key_points: List[str] = Field(default_factory=list)
    generated_at: datetime


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str = "1.0.0"


class Price5MinItem(BaseModel):
    """5-minute intraday price data item."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


# ============== API Response Models (moved from main.py) ==============

class OvernightWindowResponse(BaseModel):
    """Overnight window boundaries: start = most recent business day 4pm NY, end = now. ISO8601 UTC strings."""
    start: str
    end: str


class StorylineArticleResponse(BaseModel):
    """Article in a storyline/long-story timeline. Used by long-story timeline."""
    id: int
    ticker: str
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[datetime] = None
    relation_type: Optional[str] = None


class OvernightStoryResponse(BaseModel):
    """One overnight story for a ticker (story table). id as str for bigint-safe frontend."""
    id: str
    ticker: Optional[str] = None
    asof_date: str
    title: str
    summary: str
    topics: List[str] = []
    session_label: str
    session_confidence: Optional[float] = None
    prob_move_ge_1pct: Optional[float] = None
    prob_move_ge_2pct: Optional[float] = None
    expected_abs_move_pct: Optional[float] = None
    direction_bias: Optional[str] = None
    risk_confidence: Optional[float] = None
    risk_drivers: List[str] = []
    is_filing_related: bool = False
    created_at: Optional[datetime] = None
    latest_article_published_at: Optional[datetime] = None


class FilingCitationItem(BaseModel):
    """One filing citation: human-readable title, optional LLM summary sentence, chunk text, filing URL."""
    chunk_id: str
    filing_title: str
    summary: Optional[str] = None
    text: str
    filing_url: str
    form_type: Optional[str] = None
    filed_date: Optional[str] = None
    is_table: bool = False


class FormatFilingChunkRequest(BaseModel):
    """Request body for formatting a raw SEC filing chunk into human-readable form."""
    chunk_text: str


class FormatFilingChunkResponse(BaseModel):
    """Human-readable formatted chunk: markdown table or clear paragraphs."""
    formatted: str


class StorylineTimelineMonth(BaseModel):
    """Articles for one month in a long-story timeline."""
    month: str
    articles: List[StorylineArticleResponse]


class StorylineTimelineResponse(BaseModel):
    """Time-bucketed (by month) articles for long-story view."""
    title: Optional[str] = None
    summary: Optional[str] = None
    theme: Optional[str] = None
    total_articles: int = 0
    months: List[StorylineTimelineMonth]


class LongStoryResponse(BaseModel):
    """One long story for a ticker (long_stories row). id as str for bigint."""
    id: str
    ticker: str
    title: Optional[str] = None
    canonical_theme: Optional[str] = None
    summary: Optional[str] = None
    impact_level: Optional[str] = None
    article_count: Optional[int] = None
    created_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    latest_article_published_at: Optional[datetime] = None


class DiscoverFeedItem(BaseModel):
    """One card for Discover tab: high-impact short storylines + recently updated long stories."""
    ticker: str
    name: str
    price: float = 0.0
    change_percent: float = 0.0
    headline: str
    impact_rating: Optional[str] = None
    story_type: str
    storyline_id: Optional[str] = None
    long_story_id: Optional[str] = None
    last_updated_at: Optional[datetime] = None
    chart_data: Optional[List[float]] = None


class AskHistoryEntry(BaseModel):
    """One turn in Ask conversation for follow-up context."""
    role: str
    content: str


class CustomStoryRequest(BaseModel):
    """User-created story: question only (not persisted)."""
    ticker: Optional[str] = None
    tickers: Optional[List[str]] = None
    question: str
    history: Optional[List[AskHistoryEntry]] = None


class CustomStoryArticle(BaseModel):
    """Article returned for custom story."""
    id: int
    ticker: str
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[datetime] = None


class MacroSourceItem(BaseModel):
    """One macro brief used as RAG context."""
    topic: str
    title: Optional[str] = None
    as_of_date: Optional[str] = None


class CustomStoryResponse(BaseModel):
    """Response for POST /storylines/custom — answer + articles or macro_sources."""
    answer: str
    articles: List[CustomStoryArticle] = []
    context_type: str = "stock"
    macro_sources: Optional[List[MacroSourceItem]] = None
    detected_tickers: Optional[List[str]] = None


class StockNewsItem(BaseModel):
    """Stock news item response model."""
    id: int
    ticker: str
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: str
    published_at: datetime


class MacroNewsItem(BaseModel):
    """Macro news item response model."""
    id: int
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    source: str
    published_at: datetime
    primary_topic: Optional[str] = None
    related_tickers: Optional[List[str]] = None


class StockInfo(BaseModel):
    """Stock information model."""
    ticker: str
    name: str
    exchange: str


class StockPriceInfo(BaseModel):
    """Stock price information from Alpaca market data."""
    symbol: str
    name: Optional[str] = None
    price: float
    change: float
    changePercent: float
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volume: Optional[int] = None
    timestamp: Optional[datetime] = None
    extendedChange: Optional[float] = None
    extendedChangePercent: Optional[float] = None


class CandlestickBar(BaseModel):
    """Single candlestick bar for charting."""
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[int] = None


class HistoricalBarsResponse(BaseModel):
    """Historical bars for TradingView charts."""
    symbol: str
    bars: List[CandlestickBar]
    timeframe: str


class ConfigResponse(BaseModel):
    alpha_vantage_configured: bool
    openai_configured: bool
    watchlist_count: int
    data_sources: List[str]