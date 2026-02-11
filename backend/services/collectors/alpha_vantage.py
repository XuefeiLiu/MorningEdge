"""
Alpha Vantage data collector for stock prices and news.
Free tier: 25 requests/day
"""
import httpx
import logging
from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
from hashlib import md5

from backend.config import ALPHA_VANTAGE_API_KEY, ALPHA_VANTAGE_BASE_URL
from backend.models import NewsItem, TechnicalData, Category, ImpactLevel
from .base import BaseCollector

logger = logging.getLogger(__name__)


class AlphaVantageCollector(BaseCollector):
    """Collector for Alpha Vantage API (prices and news)."""
    
    def __init__(self):
        super().__init__("alpha_vantage", source_type="multi")
        self.api_key = ALPHA_VANTAGE_API_KEY
        self.base_url = ALPHA_VANTAGE_BASE_URL
        
        if not self.api_key:
            self.mark_unavailable("ALPHA_VANTAGE_API_KEY not configured")
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> dict:
        """Collect price data and news for symbols."""
        result = {
            "technical_data": [],
            "news": []
        }
        
        if not self.is_available:
            logger.info(f"Alpha Vantage unavailable, skipping: {self._last_error}")
            return result
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Collect price data for each symbol
                for symbol in symbols:
                    try:
                        price_data = await self._get_quote(client, symbol)
                        if price_data:
                            result["technical_data"].append(price_data)
                    except Exception as e:
                        logger.error(f"Error fetching quote for {symbol}: {e}")
                
                # Collect news (one call for all symbols)
                try:
                    news_items = await self._get_news(client, symbols, start_time, end_time)
                    result["news"].extend(news_items)
                except Exception as e:
                    logger.error(f"Error fetching news: {e}")
        except Exception as e:
            logger.error(f"Alpha Vantage collection failed: {e}")
        
        return result
    
    async def _get_quote(self, client: httpx.AsyncClient, symbol: str) -> Optional[TechnicalData]:
        """Get current quote for a symbol."""
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": self.api_key
        }
        
        response = await client.get(self.base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if "Global Quote" not in data or not data["Global Quote"]:
            logger.warning(f"No quote data for {symbol}")
            return None
        
        quote = data["Global Quote"]
        
        return TechnicalData(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            open_price=float(quote.get("02. open", 0)) or None,
            high_price=float(quote.get("03. high", 0)) or None,
            low_price=float(quote.get("04. low", 0)) or None,
            close_price=float(quote.get("05. price", 0)) or None,
            volume=int(float(quote.get("06. volume", 0))) or None,
            previous_close=float(quote.get("08. previous close", 0)) or None,
            change_percent=float(quote.get("10. change percent", "0%").rstrip("%")) or None
        )
    
    async def _get_news(
        self,
        client: httpx.AsyncClient,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """Get news for symbols."""
        # Ensure timezone-aware datetimes (caller passes UTC)
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        
        # Alpha Vantage time_from/time_to use Eastern Time (US market)
        et = ZoneInfo("America/New_York")
        start_et = start_time.astimezone(et)
        end_et = end_time.astimezone(et)
        
        # Alpha Vantage NEWS_SENTIMENT endpoint
        tickers = ",".join(symbols) 
        
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": tickers,
            "time_from": start_et.strftime("%Y%m%dT%H%M"),
            "time_to": end_et.strftime("%Y%m%dT%H%M"),
            "limit": 1000,  # Request maximum items (Alpha Vantage may still limit to 50-200 based on plan)
            "apikey": self.api_key
        }
        
        response = await client.get(self.base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Check for API errors
        if "Error Message" in data:
            logger.error(f"Alpha Vantage API error: {data['Error Message']}")
            return []
        if "Note" in data:
            logger.warning(f"Alpha Vantage API note: {data['Note']}")
            return []
        
        news_items = []
        feed = data.get("feed", [])
        
        # Log if we're hitting the limit (Alpha Vantage default is 50)
        if len(feed) == 50:
            logger.debug(f"Alpha Vantage returned 50 items (may be API limit). Total available may be higher.")
        
        for item in feed:
            try:
                # Extract symbols mentioned in this news
                item_symbols = [
                    t.get("ticker", "").upper()
                    for t in item.get("ticker_sentiment", [])
                ]
                item_symbols = [s for s in item_symbols if s in [sym.upper() for sym in symbols]]
                
                # Parse publication time
                time_str = item.get("time_published", "")
                try:
                    published_at = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                    # Set timezone to UTC (Alpha Vantage returns UTC)
                    published_at = published_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning(f"Invalid time format: {time_str}")
                    continue
                
                # Filter by date range
                if not (start_time <= published_at <= end_time):
                    continue
                
                # Generate unique ID
                news_id = md5(f"{item.get('url', '')}{time_str}".encode()).hexdigest()[:12]
                
                # Use first symbol from item_symbols, or first from requested symbols
                ticker = item_symbols[0] if item_symbols else (symbols[0].upper() if symbols else "UNKNOWN")
                
                news_items.append(NewsItem(
                    id=f"av_{news_id}",
                    ticker=ticker,
                    published_at=published_at,
                    title=item.get("title", ""),
                    summary=item.get("summary", ""),
                    url=item.get("url"),
                    source=item.get("source", "Alpha Vantage"),
                    collector="alpha_vantage"
                ))
            except Exception as e:
                logger.error(f"Error parsing news item: {e}")
                continue
        
        return news_items
    
    async def collect_news(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[NewsItem]:
        """
        Collect only news items (for use with NewsAggregator).
        
        Args:
            symbols: List of stock ticker symbols
            start_time: Start of data collection window
            end_time: End of data collection window
            
        Returns:
            List of NewsItem objects
        """
        if not self.is_available:
            logger.info(f"Alpha Vantage unavailable, skipping: {self._last_error}")
            return []
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                news_items = await self._get_news(client, symbols, start_time, end_time)
                logger.info(f"Collected {len(news_items)} news items from Alpha Vantage")
                return news_items
        except Exception as e:
            logger.error(f"Error collecting Alpha Vantage news: {e}")
            return []
    
    async def get_historical_volatility(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        days: int = 20
    ) -> Optional[float]:
        """
        Calculate historical volatility for a symbol.
        
        PLACEHOLDER: This requires TIME_SERIES_DAILY data.
        Currently returns None - implement with actual API call when needed.
        """
        # TODO: Implement with TIME_SERIES_DAILY endpoint
        # Pseudocode:
        # 1. Fetch daily prices for last {days} trading days
        # 2. Calculate daily returns: (close[i] - close[i-1]) / close[i-1]
        # 3. Calculate standard deviation of returns
        # 4. Annualize: volatility = std_dev * sqrt(252)
        return None
