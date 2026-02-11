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