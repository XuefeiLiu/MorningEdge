"""
Mock data collector for development and fallback when real sources are unavailable.

This module provides realistic mock data for all data types when:
- API keys are not configured
- External services are unavailable
- Running in development/testing mode

REAL DATA INTEGRATIONS:
- Technical/price data: Uses AlpacaMarketDataCollector when available (alpaca-py)
- Mock fallback: Used when Alpaca API is unavailable or returns no data

PLACEHOLDER NOTES:
- Replace mock news with real RSS/API calls when available
- Replace mock sentiment with social media API integration
"""
import random
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from hashlib import md5
import uuid

from backend.models import (
    NewsItem, MacroEvent, TechnicalData, SentimentData, SECFiling,
    Category, ImpactLevel
)
from .base import BaseCollector

logger = logging.getLogger(__name__)

# Import AlpacaMarketDataCollector for real price data
try:
    from .alpaca_market import AlpacaMarketDataCollector
    ALPACA_COLLECTOR_AVAILABLE = True
except ImportError:
    ALPACA_COLLECTOR_AVAILABLE = False
    logger.debug("AlpacaMarketDataCollector not available")


# Mock company data
COMPANY_INFO = {
    "AAPL": {"name": "Apple Inc.", "sector": "Technology"},
    "MSFT": {"name": "Microsoft Corporation", "sector": "Technology"},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "Technology"},
    "AMZN": {"name": "Amazon.com Inc.", "sector": "Consumer Discretionary"},
    "META": {"name": "Meta Platforms Inc.", "sector": "Technology"},
    "TSLA": {"name": "Tesla Inc.", "sector": "Consumer Discretionary"},
    "NVDA": {"name": "NVIDIA Corporation", "sector": "Technology"},
    "JPM": {"name": "JPMorgan Chase & Co.", "sector": "Financials"},
    "V": {"name": "Visa Inc.", "sector": "Financials"},
    "JNJ": {"name": "Johnson & Johnson", "sector": "Healthcare"},
}

# Mock news headlines templates
NEWS_TEMPLATES = [
    "{company} Reports Strong Q{quarter} Earnings, Beats Expectations",
    "{company} Announces New Product Launch for {year}",
    "{company} CEO Discusses Strategic Initiatives in Interview",
    "Analysts Upgrade {company} Stock Following Revenue Growth",
    "{company} Expands Operations in Asian Markets",
    "{company} Faces Regulatory Scrutiny Over Business Practices",
    "{company} Partners with Tech Giant for AI Development",
    "{company} Announces $1B Stock Buyback Program",
    "Institutional Investors Increase Stake in {company}",
    "{company} Warns of Supply Chain Challenges Ahead",
]

# Mock macro events
MACRO_TEMPLATES = [
    {"title": "Fed Holds Interest Rates Steady", "impact": ImpactLevel.HIGH},
    {"title": "Unemployment Claims Lower Than Expected", "impact": ImpactLevel.MEDIUM},
    {"title": "Consumer Confidence Index Rises", "impact": ImpactLevel.MEDIUM},
    {"title": "GDP Growth Revised Upward", "impact": ImpactLevel.HIGH},
    {"title": "Oil Prices Surge on Geopolitical Tensions", "impact": ImpactLevel.MEDIUM},
    {"title": "Core CPI Inflation Data Released", "impact": ImpactLevel.HIGH},
    {"title": "Housing Starts Beat Expectations", "impact": ImpactLevel.LOW},
    {"title": "Trade Deficit Widens in Latest Report", "impact": ImpactLevel.LOW},
]


class MockDataCollector(BaseCollector):
    """
    Mock data collector providing realistic test data with real data integration.
    
    Use this when external APIs are unavailable or for testing.
    
    REAL DATA INTEGRATIONS:
    - Technical/price data: Uses AlpacaMarketDataCollector when available
      (alpaca-py SDK with real-time market data from Alpaca API)
    
    PSEUDOCODE FOR REMAINING MOCK IMPLEMENTATIONS:
    
    For News:
        # Option 1: NewsAPI (requires API key)
        # response = await client.get("https://newsapi.org/v2/everything", params={
        #     "q": symbol,
        #     "from": start_time.isoformat(),
        #     "to": end_time.isoformat(),
        #     "apiKey": NEWS_API_KEY
        # })
        
        # Option 2: Financial news RSS feeds
        # feeds = [
        #     "https://feeds.finance.yahoo.com/rss/2.0/headline",
        #     "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        #     "https://feeds.bloomberg.com/markets/news.rss"
        # ]
    
    For Sentiment:
        # Option 1: Twitter/X API (requires API key)
        # Use tweepy or twitter-api-v2 to search for $SYMBOL cashtags
        
        # Option 2: Reddit API (free with rate limits)
        # response = await client.get(
        #     f"https://www.reddit.com/r/wallstreetbets/search.json",
        #     params={"q": symbol, "sort": "new", "t": "day"}
        # )
        
        # Option 3: StockTwits API
        # response = await client.get(
        #     f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
        # )
    """
    
    def __init__(self):
        super().__init__("mock_data")
        self._random = random.Random(42)  # Seeded for reproducibility
        
        # Initialize Alpaca collector for real price data
        self._alpaca_collector = None
        if ALPACA_COLLECTOR_AVAILABLE:
            try:
                self._alpaca_collector = AlpacaMarketDataCollector()
                if self._alpaca_collector.is_available:
                    logger.info("MockDataCollector: Alpaca real-time data enabled")
                else:
                    logger.info(f"MockDataCollector: Alpaca unavailable ({self._alpaca_collector.get_last_error()}), using mock prices")
                    self._alpaca_collector = None
            except Exception as e:
                logger.warning(f"MockDataCollector: Failed to init Alpaca collector: {e}")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> dict:
        """Generate data for all data types (uses real Alpaca data for prices when available)."""
        logger.info(f"Generating data for {len(symbols)} symbols (Alpaca: {'enabled' if self._alpaca_collector else 'disabled'})")
        
        # Get technical data (real from Alpaca or mock)
        technical_data = await self._generate_technical_data(symbols)
        
        return {
            "news": self._generate_news(symbols, start_time, end_time),
            "macro_events": self._generate_macro_events(start_time, end_time),
            "technical_data": technical_data,
            "sentiment": self._generate_sentiment(symbols, start_time),
            "sec_filings": self._generate_filings(symbols, start_time, end_time),
        }
    
    def _generate_news(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Generate mock news items."""
        news = []
        now = datetime.utcnow()
        
        for symbol in symbols:
            company = COMPANY_INFO.get(symbol, {"name": symbol, "sector": "Unknown"})
            num_news = self._random.randint(2, 5)
            
            for i in range(num_news):
                template = self._random.choice(NEWS_TEMPLATES)
                title = template.format(
                    company=company["name"],
                    quarter=self._random.randint(1, 4),
                    year=now.year
                )
                
                # Random time within window
                time_offset = timedelta(
                    hours=self._random.randint(0, int((end_time - start_time).total_seconds() / 3600))
                )
                published = start_time + time_offset
                
                news_id = md5(f"{symbol}{title}{i}".encode()).hexdigest()[:12]
                
                news.append(NewsItem(
                    id=f"mock_{news_id}",
                    ticker=symbol,
                    published_at=published,
                    title=title,
                    summary=f"Mock news summary for {company['name']}. This is placeholder content.",
                    url=f"https://example.com/news/{news_id}",
                    source="Mock News",
                    collector="mock_data"
                ))
        
        return news
    
    def _generate_macro_events(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> List[MacroEvent]:
        """Generate mock macroeconomic events."""
        events = []
        num_events = self._random.randint(2, 4)
        
        selected = self._random.sample(MACRO_TEMPLATES, min(num_events, len(MACRO_TEMPLATES)))
        
        for i, template in enumerate(selected):
            time_offset = timedelta(
                hours=self._random.randint(0, int((end_time - start_time).total_seconds() / 3600))
            )
            event_time = start_time + time_offset
            
            event_id = md5(f"macro{template['title']}{i}".encode()).hexdigest()[:12]
            
            events.append(MacroEvent(
                id=f"mock_{event_id}",
                title=template["title"],
                description=f"Mock description for {template['title']}",
                source="Mock Economic Data",
                event_time=event_time,
                actual_value=f"{self._random.uniform(0.1, 5.0):.2f}%",
                expected_value=f"{self._random.uniform(0.1, 5.0):.2f}%",
                previous_value=f"{self._random.uniform(0.1, 5.0):.2f}%",
                impact_level=template["impact"]
            ))
        
        return events
    
    async def _generate_technical_data(self, symbols: List[str]) -> List[TechnicalData]:
        """
        Generate technical data - uses real Alpaca data when available, 
        falls back to mock data otherwise.
        """
        # Try to get real data from Alpaca first
        if self._alpaca_collector:
            try:
                real_data = await self._alpaca_collector.collect(
                    symbols=symbols,
                    start_time=datetime.utcnow() - timedelta(days=1),
                    end_time=datetime.utcnow()
                )
                if real_data:
                    logger.info(f"Using real Alpaca data for {len(real_data)}/{len(symbols)} symbols")
                    # For symbols without real data, generate mock
                    real_symbols = {d.symbol for d in real_data}
                    missing_symbols = [s for s in symbols if s not in real_symbols]
                    if missing_symbols:
                        logger.debug(f"Generating mock data for missing symbols: {missing_symbols}")
                        mock_data = self._generate_mock_technical_data(missing_symbols)
                        real_data.extend(mock_data)
                    return real_data
            except Exception as e:
                logger.warning(f"Error getting Alpaca data, falling back to mock: {e}")
        
        # Fallback to mock data
        logger.debug("Using mock technical data")
        return self._generate_mock_technical_data(symbols)
    
    def _generate_mock_technical_data(self, symbols: List[str]) -> List[TechnicalData]:
        """Generate mock price and technical data."""
        data = []
        
        for symbol in symbols:
            # Generate realistic price data
            base_price = self._random.uniform(50, 500)
            volatility = self._random.uniform(0.01, 0.05)
            
            open_price = base_price * (1 + self._random.uniform(-volatility, volatility))
            close_price = base_price * (1 + self._random.uniform(-volatility, volatility))
            high_price = max(open_price, close_price) * (1 + self._random.uniform(0, volatility))
            low_price = min(open_price, close_price) * (1 - self._random.uniform(0, volatility))
            
            previous_close = base_price * (1 + self._random.uniform(-volatility, volatility))
            change_percent = ((close_price - previous_close) / previous_close) * 100
            
            # Calculate support/resistance
            support = low_price * 0.98
            resistance = high_price * 1.02
            
            data.append(TechnicalData(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                open_price=round(open_price, 2),
                high_price=round(high_price, 2),
                low_price=round(low_price, 2),
                close_price=round(close_price, 2),
                volume=self._random.randint(1000000, 50000000),
                previous_close=round(previous_close, 2),
                change_percent=round(change_percent, 2),
                support_level=round(support, 2),
                resistance_level=round(resistance, 2),
                volatility=round(volatility * 100, 2)
            ))
        
        return data
    
    def _generate_sentiment(
        self,
        symbols: List[str],
        timestamp: datetime
    ) -> List[SentimentData]:
        """Generate mock sentiment data."""
        sentiment_data = []
        
        for symbol in symbols:
            sentiment_data.append(SentimentData(
                symbol=symbol,
                source="Mock Social Media",
                timestamp=timestamp,
                sentiment_score=self._random.uniform(-0.5, 0.8),
                volume=self._random.randint(100, 10000),
                trending_topics=[f"${symbol}", "earnings", "growth"]
            ))
        
        return sentiment_data
    
    def _generate_filings(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[SECFiling]:
        """Generate mock SEC filings."""
        filings = []
        form_types = ["8-K", "10-Q", "4", "13F"]
        
        for symbol in symbols:
            if self._random.random() < 0.3:  # 30% chance of filing
                form = self._random.choice(form_types)
                
                time_offset = timedelta(
                    hours=self._random.randint(0, int((end_time - start_time).total_seconds() / 3600))
                )
                filed_date = start_time + time_offset
                
                filing_id = md5(f"{symbol}{form}{filed_date}".encode()).hexdigest()[:12]
                
                impact = ImpactLevel.HIGH if form in ["8-K", "10-Q"] else ImpactLevel.MEDIUM
                
                filings.append(SECFiling(
                    id=f"mock_{filing_id}",
                    symbol=symbol,
                    form_type=form,
                    filed_date=filed_date,
                    description=f"Mock {form} filing for {symbol}",
                    url=f"https://example.com/sec/{filing_id}",
                    impact_level=impact
                ))
        
        return filings
