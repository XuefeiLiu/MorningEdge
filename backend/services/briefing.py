"""
Briefing report generation and trading direction heuristics.
"""
import logging
from datetime import datetime, timedelta, time
from typing import List, Optional, Dict, Any
import asyncio
import traceback

try:
    from zoneinfo import ZoneInfo
except ImportError:
    try:
        from backports.zoneinfo import ZoneInfo
    except ImportError:
        # Fallback: use pytz or a simple UTC offset
        ZoneInfo = None

from backend.config import MARKET_CLOSE_TIME, MARKET_OPEN_TIME
from backend.models import (
    BriefingReport, StockImpactSummary, NewsItem, MacroEvent,
    TechnicalData, SentimentData, SECFiling,
    ImpactLevel, TradingDirection, Category
)
from backend.services.collectors import (
    AlphaVantageCollector, SECEdgarCollector, NasdaqRSSCollector,
    FREDCollector, NewsNowCollector, FinancialDatasetsCollector,
    NewsSourceConfig, news_registry
)
from backend.services.news_aggregator import NewsAggregator
from backend.config import NEWS_SOURCES, NEWS_AGGREGATION, FINANCIAL_DATASETS_API_KEY
from backend.services.filters import TimeWindowFilter
from backend.services.news_filters import FilterFactory, KeywordRelevanceFilter
from backend.services.tagging import ImpactTagger, CategoryTagger, DataSorter

logger = logging.getLogger(__name__)


class TimeWindowCalculator:
    """Calculate the data collection time window based on market hours."""
    
    def __init__(self, timezone: str = "America/New_York"):
        if ZoneInfo is not None:
            try:
                self.tz = ZoneInfo(timezone)
            except Exception:
                self.tz = None
        else:
            self.tz = None
    
    def get_overnight_window(self) -> tuple[datetime, datetime]:
        """
        Get the time window from last market close to now.
        
        For pre-market briefing:
        - Start: Previous trading day's market close (4:00 PM ET)
        - End: Current time
        
        Returns:
            Tuple of (start_time, end_time) in UTC
        """
        # Handle case where timezone is not available
        if self.tz is None:
            now = datetime.utcnow()
            # Simple fallback: last 16 hours
            return (now - timedelta(hours=16), now)
        
        now = datetime.now(self.tz)
        today = now.date()
        
        # Determine last market close
        if now.time() < MARKET_OPEN_TIME:
            # Before market open today, use yesterday's close
            if today.weekday() == 0:  # Monday
                # Use Friday's close
                last_close_date = today - timedelta(days=3)
            else:
                last_close_date = today - timedelta(days=1)
        else:
            # After market open, still use yesterday's close for overnight data
            if today.weekday() == 0:  # Monday
                last_close_date = today - timedelta(days=3)
            elif today.weekday() == 6:  # Sunday
                last_close_date = today - timedelta(days=2)
            elif today.weekday() == 5:  # Saturday
                last_close_date = today - timedelta(days=1)
            else:
                last_close_date = today - timedelta(days=1)
        
        # Handle weekends - market closed
        while last_close_date.weekday() >= 5:  # Saturday or Sunday
            last_close_date -= timedelta(days=1)
        
        start_time = datetime.combine(last_close_date, MARKET_CLOSE_TIME, tzinfo=self.tz)
        end_time = now
        
        # Convert to UTC for API calls
        return (
            start_time.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
            end_time.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        )
    
    def get_custom_window(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> tuple[datetime, datetime]:
        """Get a custom time window, with defaults for missing values."""
        if start and end:
            return (start, end)
        
        default_start, default_end = self.get_overnight_window()
        return (start or default_start, end or default_end)


class TradingDirectionAnalyzer:
    """
    Analyze collected data to determine potential trading direction.
    
    This is a heuristic-based system that combines:
    - News sentiment (positive/negative headlines)
    - Technical indicators (price movement, support/resistance)
    - Market sentiment scores
    - SEC filing impact
    """
    
    # Weight factors for different signals
    WEIGHTS = {
        "news_sentiment": 0.25,
        "technical": 0.30,
        "market_sentiment": 0.20,
        "sec_filings": 0.15,
        "macro": 0.10
    }
    
    def analyze(
        self,
        symbol: str,
        news: List[NewsItem],
        technical: Optional[TechnicalData],
        sentiment: Optional[SentimentData],
        filings: List[SECFiling],
        macro_events: List[MacroEvent]
    ) -> tuple[TradingDirection, float, List[str]]:
        """
        Analyze all data for a symbol and determine trading direction.
        
        Returns:
            Tuple of (direction, confidence_score, key_drivers)
        """
        signals = []
        drivers = []
        
        # News sentiment signal (-1 to 1)
        news_signal = self._analyze_news_sentiment(news, symbol)
        if news_signal != 0:
            signals.append(("news_sentiment", news_signal))
            if news_signal > 0:
                drivers.append(f"Positive news sentiment ({len(news)} items)")
            else:
                drivers.append(f"Negative news sentiment ({len(news)} items)")
        
        # Technical signal
        tech_signal = self._analyze_technical(technical)
        if tech_signal != 0:
            signals.append(("technical", tech_signal))
            if technical:
                if tech_signal > 0:
                    drivers.append(f"Bullish price action (+{technical.change_percent:.1f}%)")
                else:
                    drivers.append(f"Bearish price action ({technical.change_percent:.1f}%)")
        
        # Market sentiment signal
        if sentiment:
            sent_signal = sentiment.sentiment_score
            signals.append(("market_sentiment", sent_signal))
            if sent_signal > 0.2:
                drivers.append("Positive social sentiment")
            elif sent_signal < -0.2:
                drivers.append("Negative social sentiment")
        
        # SEC filing signal
        filing_signal = self._analyze_filings(filings)
        if filing_signal != 0:
            signals.append(("sec_filings", filing_signal))
            high_impact = [f for f in filings if f.impact_level == ImpactLevel.HIGH]
            if high_impact:
                drivers.append(f"High-impact SEC filing: {high_impact[0].form_type}")
        
        # Macro signal (affects all stocks)
        macro_signal = self._analyze_macro(macro_events)
        if macro_signal != 0:
            signals.append(("macro", macro_signal))
            drivers.append("Significant macro events")
        
        # Calculate weighted score
        total_score = 0
        total_weight = 0
        
        for signal_type, value in signals:
            weight = self.WEIGHTS.get(signal_type, 0.1)
            total_score += value * weight
            total_weight += weight
        
        if total_weight > 0:
            final_score = total_score / total_weight
        else:
            final_score = 0
        
        # Determine direction and confidence
        confidence = min(abs(final_score), 1.0)
        
        if final_score > 0.15:
            direction = TradingDirection.BUY
        elif final_score < -0.15:
            direction = TradingDirection.SELL
        else:
            direction = TradingDirection.HOLD
        
        return direction, confidence, drivers[:5]  # Limit drivers
    
    def _analyze_news_sentiment(
        self,
        news: List[NewsItem],
        symbol: str
    ) -> float:
        """Analyze news sentiment for a symbol."""
        if not news:
            return 0
        
        # Filter news for this symbol
        symbol_news = [n for n in news if symbol.upper() == n.ticker.upper()]
        if not symbol_news:
            return 0
        
        # Simple keyword-based sentiment
        positive_words = [
            "beat", "exceed", "strong", "growth", "upgrade", "buy",
            "positive", "profit", "gain", "success", "bullish"
        ]
        negative_words = [
            "miss", "decline", "weak", "loss", "downgrade", "sell",
            "negative", "cut", "fail", "bearish", "warning"
        ]
        
        total_score = 0
        for item in symbol_news:
            text = f"{item.title} {item.summary or ''}".lower()
            
            pos_count = sum(1 for w in positive_words if w in text)
            neg_count = sum(1 for w in negative_words if w in text)
            
            if pos_count + neg_count > 0:
                item_score = (pos_count - neg_count) / (pos_count + neg_count)
                # Weight by impact level (calculate on the fly since NewsItem doesn't have impact_level)
                # Create ImpactTagger instance to calculate impact
                impact_tagger = ImpactTagger()
                impact_level = impact_tagger._calculate_news_impact(item)
                if impact_level == ImpactLevel.HIGH:
                    item_score *= 1.5
                total_score += item_score
        
        return max(min(total_score / len(symbol_news), 1), -1)
    
    def _analyze_technical(self, technical: Optional[TechnicalData]) -> float:
        """Analyze technical data for trading signal."""
        if not technical:
            return 0
        
        signal = 0
        
        # Price change signal
        if technical.change_percent:
            if technical.change_percent > 2:
                signal += 0.5
            elif technical.change_percent > 0:
                signal += 0.2
            elif technical.change_percent < -2:
                signal -= 0.5
            elif technical.change_percent < 0:
                signal -= 0.2
        
        # Support/Resistance analysis
        if technical.close_price and technical.support_level and technical.resistance_level:
            price = technical.close_price
            support = technical.support_level
            resistance = technical.resistance_level
            
            # Near support = potential bounce (bullish)
            if price < support * 1.02:
                signal += 0.3
            # Near resistance = potential rejection (bearish)
            elif price > resistance * 0.98:
                signal -= 0.3
        
        return max(min(signal, 1), -1)
    
    def _analyze_filings(self, filings: List[SECFiling]) -> float:
        """Analyze SEC filings for trading signal."""
        if not filings:
            return 0
        
        signal = 0
        
        for filing in filings:
            # 8-K can be positive or negative (need content analysis)
            # For now, treat high-impact filings as slightly negative (uncertainty)
            if filing.impact_level == ImpactLevel.HIGH:
                if "acquisition" in (filing.description or "").lower():
                    signal += 0.2
                else:
                    signal -= 0.1  # Uncertainty
        
        return max(min(signal, 1), -1)
    
    def _analyze_macro(self, events: List[MacroEvent]) -> float:
        """Analyze macro events for market-wide signal."""
        if not events:
            return 0
        
        signal = 0
        
        for event in events:
            title_lower = event.title.lower()
            
            # Rate decisions
            if "rate" in title_lower:
                if "cut" in title_lower or "lower" in title_lower:
                    signal += 0.3
                elif "hike" in title_lower or "raise" in title_lower:
                    signal -= 0.3
            
            # Economic data
            if "beat" in title_lower or "strong" in title_lower:
                signal += 0.1
            elif "miss" in title_lower or "weak" in title_lower:
                signal -= 0.1
        
        return max(min(signal, 1), -1)


class BriefingGenerator:
    """Generates comprehensive pre-market briefing reports."""
    
    def __init__(self):
        self.time_calculator = TimeWindowCalculator()
        # Use keyword filter with lower relevance threshold to avoid filtering out too many items
        # The default 0.3 might be too strict for news that doesn't explicitly mention symbols
        self.news_filter = KeywordRelevanceFilter(relevance_threshold=0.1)
        self.impact_tagger = ImpactTagger()
        self.category_tagger = CategoryTagger()
        self.sorter = DataSorter()
        self.direction_analyzer = TradingDirectionAnalyzer()
        
        # Initialize collectors
        self.alpha_vantage = AlphaVantageCollector()
        self.sec_edgar = SECEdgarCollector()
        self.nasdaq_rss = NasdaqRSSCollector()
        self.fred = FREDCollector()
        
        # Initialize new collectors
        self.newsnow = NewsNowCollector(
            platforms=NEWS_SOURCES.get("newsnow", {}).get("platforms", {})
        )
        self.financial_datasets = FinancialDatasetsCollector(
            api_key=FINANCIAL_DATASETS_API_KEY
        )
        
        # Register collectors in news registry
        self._register_collectors()
        
        # Log registered collectors for debugging
        registered = news_registry.get_all_source_ids()
        logger.info(f"Registered {len(registered)} collectors in news registry: {registered}")
        for source_id in registered:
            config = news_registry.get_config(source_id)
            collector = news_registry.get_collector(source_id)
            logger.info(f"  - {source_id}: enabled={config.enabled if config else False}, available={collector.is_available if collector else False}")
        
        # Initialize news aggregator
        self.news_aggregator = NewsAggregator(config=NEWS_AGGREGATION)
    
    def _register_collectors(self):
        """Register all news collectors in the registry."""
        # Register Nasdaq RSS
        nasdaq_config = NEWS_SOURCES.get("nasdaq_rss", {})
        news_registry.register(
            self.nasdaq_rss,
            NewsSourceConfig(
                enabled=nasdaq_config.get("enabled", True),
                priority=nasdaq_config.get("priority", 1),
                max_items_per_symbol=nasdaq_config.get("max_items_per_symbol", 20),
                freshness_days=nasdaq_config.get("freshness_days"),
                reliability_score=nasdaq_config.get("reliability_score", 0.8),
                name=nasdaq_config.get("name", "Nasdaq RSS"),
                source_type=nasdaq_config.get("source_type", "news")
            )
        )
        
        # Register Alpha Vantage (for news)
        av_config = NEWS_SOURCES.get("alpha_vantage", {})
        news_registry.register(
            self.alpha_vantage,
            NewsSourceConfig(
                enabled=av_config.get("enabled", True),
                priority=av_config.get("priority", 2),
                max_items_per_symbol=av_config.get("max_items_per_symbol", 50),
                reliability_score=av_config.get("reliability_score", 0.7),
                name=av_config.get("name", "Alpha Vantage"),
                source_type=av_config.get("source_type", "multi"),
                requires_api_key=av_config.get("requires_api_key", False)
            )
        )
        
        # Register NewsNow
        newsnow_config = NEWS_SOURCES.get("newsnow", {})
        if newsnow_config.get("enabled", True):
            news_registry.register(
                self.newsnow,
                NewsSourceConfig(
                    enabled=True,
                    priority=newsnow_config.get("priority", 3),
                    max_items_per_symbol=newsnow_config.get("max_items_per_symbol", 50),
                    reliability_score=newsnow_config.get("reliability_score", 0.6),
                    name=newsnow_config.get("name", "NewsNow"),
                    source_type=newsnow_config.get("source_type", "news"),
                    extra_config=newsnow_config
                )
            )
            logger.info(f"NewsNow collector registered with {len(self.newsnow.platforms)} platforms")
        else:
            logger.info("NewsNow collector disabled in config")
        
        # Register Financial Datasets
        fd_config = NEWS_SOURCES.get("financial_datasets", {})
        if fd_config.get("enabled", False):
            news_registry.register(
                self.financial_datasets,
                NewsSourceConfig(
                    enabled=True,
                    priority=fd_config.get("priority", 4),
                    max_items_per_symbol=fd_config.get("max_items_per_symbol", 100),
                    reliability_score=fd_config.get("reliability_score", 0.8),
                    name=fd_config.get("name", "Financial Datasets"),
                    source_type=fd_config.get("source_type", "news"),
                    requires_api_key=fd_config.get("requires_api_key", False)
                )
            )
            logger.info(f"Financial Datasets collector registered (API key: {'set' if self.financial_datasets.api_key else 'not set'})")
        else:
            logger.info("Financial Datasets collector disabled (API key not set or disabled in config)")
    
    async def generate(
        self,
        symbols: List[str],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> BriefingReport:
        """
        Generate a complete pre-market briefing report.
        
        Args:
            symbols: List of stock symbols to include
            start_time: Optional custom start time
            end_time: Optional custom end time
            
        Returns:
            Complete BriefingReport with all data and summaries
        """
        # Calculate time window
        try:
            window_start, window_end = self.time_calculator.get_custom_window(
                start_time, end_time
            )
        except Exception:
            # Fallback to simple UTC times
            window_end = datetime.utcnow()
            window_start = window_end - timedelta(hours=16)
        
        logger.info(f"Generating briefing for {len(symbols)} symbols")
        logger.info(f"Time window: {window_start} to {window_end}")
        
        # Reset filter state for new report
        # Reset is not needed for new filter (no state to reset)
        pass
        
        # Collect data from all sources
        try:
            raw_data = await self._collect_real_data(symbols, window_start, window_end)
        except asyncio.CancelledError as ce:
            logger.error(f"Briefing generation was cancelled: {ce}")
            raise  # Re-raise CancelledError to propagate properly
        except Exception as e:
            logger.warning(f"Data collection failed, returning empty report: {e}")
            raw_data = {
                "news": [],
                "macro_events": [],
                "technical_data": [],
                "sentiment": [],
                "sec_filings": [],
            }
        
        # Process and filter data
        processed = await self._process_data(raw_data, symbols, window_start, window_end)
        
        # Generate per-stock summaries
        stock_summaries = self._generate_stock_summaries(symbols, processed)
        
        # Count high-impact items
        high_impact_count = (
            self.sorter.get_high_impact_count(processed["news"]) +
            self.sorter.get_high_impact_count(processed["macro"]) +
            self.sorter.get_high_impact_count(processed["filings"])
        )
        
        # Generate risk warnings
        risk_warnings = self._generate_risk_warnings(processed, stock_summaries)
        
        # Build report
        report = BriefingReport(
            generated_at=datetime.utcnow(),
            time_window_start=window_start,
            time_window_end=window_end,
            watchlist=symbols,
            company_news=processed["news"],
            macro_events=processed["macro"],
            technical_data=processed["technical"],
            market_sentiment=processed["sentiment"],
            sec_filings=processed["filings"],
            stock_summaries=stock_summaries,
            high_impact_items_count=high_impact_count,
            risk_warnings=risk_warnings
        )
        
        return report
    
    async def _collect_real_data(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> dict:
        """Collect data from real sources."""
        raw_data = {
            "news": [],
            "macro_events": [],
            "technical_data": [],
            "sentiment": [],
            "sec_filings": []
        }
        
        # Collect news - use direct collectors first for reliability, then aggregator for additional sources
        aggregated_news = []
        
        # Collect from fast/reliable sources directly first (Nasdaq RSS, Financial Datasets, NewsNow)
        logger.info("Collecting from fast sources directly...")
        if self.nasdaq_rss.is_available:
            try:
                nasdaq_news = await asyncio.wait_for(
                    self.nasdaq_rss.collect(symbols, start_time, end_time),
                    timeout=10.0
                )
                aggregated_news.extend(nasdaq_news)
                logger.info(f"✓ Nasdaq RSS collected {len(nasdaq_news)} items directly")
            except Exception as e:
                logger.warning(f"✗ Nasdaq RSS direct collection failed: {e}")
        
        if self.financial_datasets.is_available and self.financial_datasets.api_key:
            try:
                fd_news = await asyncio.wait_for(
                    self.financial_datasets.collect(symbols, start_time, end_time),
                    timeout=15.0
                )
                aggregated_news.extend(fd_news)
                logger.info(f"✓ Financial Datasets collected {len(fd_news)} items directly")
            except Exception as e:
                logger.warning(f"✗ Financial Datasets direct collection failed: {e}")
        
        # Collect NewsNow directly for macro events (with reduced timeout)
        if self.newsnow.is_available:
            try:
                logger.info("Collecting NewsNow items for macro events...")
                # Reduced timeout from 60s to 30s - if it takes longer, we continue without NewsNow
                newsnow_items = await asyncio.wait_for(
                    self.newsnow.collect(symbols, start_time, end_time),
                    timeout=30.0  # Reduced timeout - continue with partial results if timeout
                )
                aggregated_news.extend(newsnow_items)
                logger.info(f"✓ NewsNow collected {len(newsnow_items)} items directly (will be converted to macro events)")
            except (asyncio.TimeoutError, asyncio.CancelledError) as e:
                # CancelledError can be raised when wait_for timeout expires (Python 3.11+)
                # Treat both timeout and cancellation as "NewsNow took too long" and continue
                logger.warning(f"✗ NewsNow collection timed out or was cancelled after 30 seconds: {type(e).__name__}")
                # Continue without NewsNow items - don't re-raise, just proceed
            except Exception as e:
                logger.warning(f"✗ NewsNow direct collection failed: {e}")
        
        # Then try aggregator for any additional sources (if any are registered but not called directly)
        # Note: NewsNow is already collected directly above, so aggregator will skip it or add duplicates
        # This is fine - duplicates will be handled by deduplication
        try:
            logger.info("Starting news aggregation for any additional sources...")
            additional_news = await asyncio.wait_for(
                self.news_aggregator.collect_for_symbols(symbols, start_time, end_time),
                timeout=20.0  # Shorter timeout since main sources are already collected
            )
            logger.info(f"✓ News aggregator completed, returned {len(additional_news)} additional items")
            aggregated_news.extend(additional_news)
        except asyncio.TimeoutError:
            logger.warning("News aggregator timed out after 20 seconds, continuing with direct sources only")
        except asyncio.CancelledError as ce:
            logger.error(f"News aggregator was cancelled: {ce}")
            raise  # Re-raise to propagate
        except Exception as e:
            logger.warning(f"News aggregator failed: {e}, continuing with direct sources only")
        
        # Separate NewsNow items (macro events) from regular news
        newsnow_items = []
        regular_news = []
        newsnow_count = 0
        macro_event_count = 0
        
        logger.info(f"Processing {len(aggregated_news)} total items to separate news vs macro events...")
        for item in aggregated_news:
            is_newsnow = item.source.startswith("NewsNow-")
            # Check if it should be treated as macro event based on source
            # NewsItem doesn't have category field, so we use source check
            is_macro = is_newsnow
            
            if is_newsnow:
                newsnow_count += 1
                macro_event_count += 1
            
            if is_macro:
                # Convert NewsItem to MacroEvent for NewsNow items
                # Calculate impact level on the fly since NewsItem doesn't have impact_level field
                calculated_impact = self.impact_tagger._calculate_news_impact(item)
                macro_event = MacroEvent(
                    id=item.id,
                    title=item.title,
                    description=item.summary,
                    source=item.source,
                    event_time=item.published_at,
                    indicator=None,
                    actual_value=None,
                    expected_value=None,
                    previous_value=None,
                    impact_level=calculated_impact
                )
                newsnow_items.append(macro_event)
                logger.debug(f"Converted to macro event: {item.title[:50]} (source: {item.source})")
            else:
                regular_news.append(item)
        
        logger.info(f"Separated items: {len(regular_news)} regular news, {len(newsnow_items)} macro events (NewsNow sources: {newsnow_count}, MACRO_EVENT category: {macro_event_count})")
        
        raw_data["news"] = regular_news
        raw_data["macro_events"].extend(newsnow_items)
        
        # Collect other data types in parallel
        tasks = []
        
        # Alpha Vantage (technical data only, news already collected)
        if self.alpha_vantage.is_available:
            tasks.append(("alpha_vantage", self.alpha_vantage.collect(symbols, start_time, end_time)))
        
        # SEC EDGAR
        tasks.append(("sec", self.sec_edgar.collect(symbols, start_time, end_time)))
        
        # FRED macro data
        tasks.append(("fred", self.fred.collect(symbols, start_time, end_time)))
        
        # Execute all tasks with a global timeout to prevent hanging
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[t[1] for t in tasks],
                    return_exceptions=True
                ),
                timeout=30.0  # 30 second global timeout
            )
        except asyncio.TimeoutError:
            logger.error("Data collection timed out")
            results = [Exception("Timeout") for _ in tasks]
        except asyncio.CancelledError as ce:
            logger.error(f"Data collection tasks were cancelled: {ce}")
            raise  # Re-raise to propagate
        
        # Process results
        for i, (source_name, _) in enumerate(tasks):
            result = results[i]
            
            if isinstance(result, Exception):
                logger.error(f"Error collecting from {source_name}: {result}")
                continue
            
            if source_name == "alpha_vantage":
                # Only get technical data, news already collected via aggregator
                if isinstance(result, dict):
                    raw_data["technical_data"].extend(result.get("technical_data", []))
            elif source_name == "sec":
                raw_data["sec_filings"].extend(result if result else [])
            elif source_name == "fred":
                raw_data["macro_events"].extend(result if result else [])
        
        return raw_data
    
    async def _process_data(
        self,
        raw_data: dict,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> dict:
        """Filter, tag, and sort collected data."""
        time_filter = TimeWindowFilter(start_time, end_time)
        
        # Process news
        news = raw_data.get("news", [])
        
        # Only filter if we have news items
        if news:
            # Filter news for relevance to any of the symbols
            # Since new filters work per-ticker, filter for each symbol and combine
            filtered_news = []
            seen_ids = set()
            for symbol in symbols:
                symbol_news = await self.news_filter.filter(news, symbol)
                for item in symbol_news:
                    if item.id not in seen_ids:
                        filtered_news.append(item)
                        seen_ids.add(item.id)
            news = filtered_news
            
            news = self.impact_tagger.tag_news(news)
            news = self.category_tagger.tag_news(news)
            news = self.sorter.sort_by_impact(news)
        else:
            logger.warning(f"No news items to process for symbols: {symbols}")
        
        # Process macro events
        macro = raw_data.get("macro_events", [])
        macro = self.impact_tagger.tag_macro_events(macro)
        macro = self.sorter.sort_by_impact(macro)
        
        # Process SEC filings
        filings = raw_data.get("sec_filings", [])
        # Filter filings by symbols (simple symbol matching)
        target_symbols_set = set(s.upper() for s in symbols)
        filings = [f for f in filings if f.symbol.upper() in target_symbols_set]
        filings = self.impact_tagger.tag_filings(filings)
        filings = self.sorter.sort_by_impact(filings)
        
        # Technical data (no filtering needed)
        technical = raw_data.get("technical_data", [])
        
        # Sentiment data
        sentiment = raw_data.get("sentiment", [])
        
        return {
            "news": news,
            "macro": macro,
            "filings": filings,
            "technical": technical,
            "sentiment": sentiment
        }
    
    def _generate_stock_summaries(
        self,
        symbols: List[str],
        processed: dict
    ) -> List[StockImpactSummary]:
        """Generate per-stock impact summaries."""
        summaries = []
        
        for symbol in symbols:
            # Get data for this symbol
            symbol_news = [n for n in processed["news"] if symbol.upper() == n.ticker.upper()]
            symbol_filings = [f for f in processed["filings"] if f.symbol == symbol]
            symbol_tech = next(
                (t for t in processed["technical"] if t.symbol == symbol),
                None
            )
            symbol_sentiment = next(
                (s for s in processed["sentiment"] if s.symbol == symbol),
                None
            )
            
            # Analyze trading direction
            direction, confidence, drivers = self.direction_analyzer.analyze(
                symbol,
                symbol_news,
                symbol_tech,
                symbol_sentiment,
                symbol_filings,
                processed["macro"]
            )
            
            # Generate risk warnings for this stock
            stock_risks = []
            if any(f.impact_level == ImpactLevel.HIGH for f in symbol_filings):
                stock_risks.append("High-impact SEC filing detected")
            if symbol_tech and symbol_tech.volatility and symbol_tech.volatility > 3:
                stock_risks.append("High volatility warning")
            if symbol_sentiment and symbol_sentiment.sentiment_score < -0.3:
                stock_risks.append("Negative social sentiment")
            
            summary = StockImpactSummary(
                symbol=symbol,
                trading_direction=direction,
                confidence_score=confidence,
                key_drivers=drivers,
                news_count=len(symbol_news),
                filings_count=len(symbol_filings),
                sentiment_score=symbol_sentiment.sentiment_score if symbol_sentiment else None,
                technical_summary=symbol_tech,
                support_level=symbol_tech.support_level if symbol_tech else None,
                resistance_level=symbol_tech.resistance_level if symbol_tech else None,
                risk_warnings=stock_risks
            )
            
            summaries.append(summary)
        
        return summaries
    
    def _generate_risk_warnings(
        self,
        processed: dict,
        stock_summaries: List[StockImpactSummary]
    ) -> List[str]:
        """Generate overall risk warnings."""
        warnings = []
        
        # Check for significant macro events
        high_impact_macro = [
            e for e in processed["macro"]
            if e.impact_level == ImpactLevel.HIGH
        ]
        if high_impact_macro:
            warnings.append(
                f"Major economic event: {high_impact_macro[0].title}"
            )
        
        # Check for multiple sell signals
        sell_count = sum(
            1 for s in stock_summaries
            if s.trading_direction == TradingDirection.SELL
        )
        if sell_count > len(stock_summaries) / 2:
            warnings.append("Multiple stocks showing bearish signals")
        
        # Check for high volatility across stocks
        high_vol_count = sum(
            1 for s in stock_summaries
            if s.technical_summary and
               s.technical_summary.volatility and
               s.technical_summary.volatility > 3
        )
        if high_vol_count > 2:
            warnings.append("Elevated market volatility detected")
        
        return warnings


# Global instance for easy access
briefing_generator = BriefingGenerator()
