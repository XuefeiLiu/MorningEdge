"""
Alpaca Market Data Collector for real-time stock price data.

Uses alpaca-py SDK to fetch:
- Snapshots (latest trade, quote, minute bar, daily bar, previous daily bar)
- Latest quotes (bid/ask prices)
- Latest bars (OHLCV data)
- Historical bar data

API Documentation: https://alpaca.markets/sdks/python/market_data.html
"""
import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from backend.models import TechnicalData
from .base import BaseCollector

logger = logging.getLogger(__name__)

# Alpaca imports - wrapped in try/except for graceful degradation
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import (
        StockLatestQuoteRequest,
        StockLatestBarRequest,
        StockBarsRequest,
        StockSnapshotRequest,
    )
    from alpaca.data.timeframe import TimeFrame
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    logger.warning("alpaca-py not installed. Run: pip install alpaca-py")


class AlpacaMarketDataCollector(BaseCollector):
    """
    Collector for real-time stock market data using Alpaca API.

    Provides:
    - Latest quotes (bid/ask)
    - Latest bars (OHLCV)
    - Historical bar data

    API keys should be set in .env:
        alpaca-api-key=YOUR_API_KEY
        alpaca-secret-key=YOUR_SECRET_KEY
    """

    def __init__(self):
        super().__init__("alpaca_market", source_type="technical")

        if not ALPACA_AVAILABLE:
            self.mark_unavailable("alpaca-py library not installed")
            return

        # Load API keys from environment (uses hyphens per user's .env format)
        self.api_key = os.getenv("alpaca-api-key", "").strip().strip("'\"")
        self.secret_key = os.getenv("alpaca-secret-key", "").strip().strip("'\"")

        if not self.api_key or not self.secret_key:
            self.mark_unavailable("Alpaca API keys not configured in .env")
            return

        try:
            # Initialize the stock historical data client
            self.client = StockHistoricalDataClient(
                api_key=self.api_key,
                secret_key=self.secret_key
            )
            logger.info("AlpacaMarketDataCollector initialized successfully")
        except Exception as e:
            self.mark_unavailable(f"Failed to initialize Alpaca client: {e}")

    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[TechnicalData]:
        """
        Collect real-time market data for the given symbols using Alpaca snapshots.

        Args:
            symbols: List of stock ticker symbols (e.g., ["AAPL", "MSFT"])
            start_time: Start of the data collection window
            end_time: End of the data collection window

        Returns:
            List of TechnicalData objects with current market prices
        """
        if not self.is_available:
            logger.warning(
                f"AlpacaMarketDataCollector unavailable: {self._last_error}"
            )
            return []

        technical_data = []

        try:
            # Use snapshot API - returns daily_bar, previous_daily_bar,
            # latest_trade, latest_quote, and minute_bar all in one call
            snapshots = self._get_snapshots(symbols)

            for symbol in symbols:
                try:
                    snapshot = snapshots.get(symbol)
                    if not snapshot:
                        logger.debug(f"No snapshot for {symbol}")
                        continue

                    data = self._build_technical_data_from_snapshot(
                        symbol=symbol,
                        snapshot=snapshot
                    )
                    if data:
                        technical_data.append(data)
                        logger.debug(
                            f"Collected data for {symbol}: "
                            f"close=${data.close_price}, "
                            f"prev_close=${data.previous_close}, "
                            f"change={data.change_percent}%"
                        )
                except Exception as e:
                    logger.warning(f"Error building data for {symbol}: {e}")

            logger.info(
                f"Collected technical data for "
                f"{len(technical_data)}/{len(symbols)} symbols"
            )

        except Exception as e:
            logger.error(
                f"Error collecting Alpaca market data: {e}",
                exc_info=True
            )

        return technical_data

    def _get_snapshots(self, symbols: List[str]) -> Dict:
        """Fetch snapshots for multiple symbols (daily bar + previous daily bar + latest trade)."""
        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbols)
            snapshots = self.client.get_stock_snapshot(request)
            return snapshots
        except Exception as e:
            logger.warning(f"Error fetching snapshots: {e}")
            return {}

    def _build_technical_data_from_snapshot(
        self,
        symbol: str,
        snapshot: object
    ) -> Optional[TechnicalData]:
        """
        Build TechnicalData from an Alpaca Snapshot object.

        Snapshot contains: daily_bar, previous_daily_bar, latest_trade,
        latest_quote, minute_bar.
        """
        daily_bar = getattr(snapshot, 'daily_bar', None)
        prev_daily_bar = getattr(snapshot, 'previous_daily_bar', None)
        latest_trade = getattr(snapshot, 'latest_trade', None)

        if not daily_bar:
            logger.debug(f"No daily bar in snapshot for {symbol}")
            return None

        try:
            open_price = float(daily_bar.open)
            high_price = float(daily_bar.high)
            low_price = float(daily_bar.low)
            close_price = float(daily_bar.close)
            volume = int(daily_bar.volume)

            # Use previous daily bar for change calculation
            previous_close = None
            change_percent = None
            if prev_daily_bar:
                previous_close = float(prev_daily_bar.close)
                if previous_close > 0:
                    change_percent = (
                        (close_price - previous_close) / previous_close
                    ) * 100

            support_level = low_price * 0.98
            resistance_level = high_price * 1.02

            volatility = None
            if close_price > 0:
                volatility = ((high_price - low_price) / close_price) * 100

            return TechnicalData(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                open_price=round(open_price, 2),
                high_price=round(high_price, 2),
                low_price=round(low_price, 2),
                close_price=round(close_price, 2),
                volume=volume,
                previous_close=(
                    round(previous_close, 2) if previous_close else None
                ),
                change_percent=(
                    round(change_percent, 2) if change_percent is not None
                    else None
                ),
                support_level=round(support_level, 2),
                resistance_level=round(resistance_level, 2),
                volatility=round(volatility, 2) if volatility else None
            )
        except Exception as e:
            logger.warning(
                f"Error building TechnicalData from snapshot for {symbol}: {e}"
            )
            return None

    @staticmethod
    def _is_market_open() -> bool:
        """Check if US stock market is currently in regular trading hours."""
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo

        et_now = datetime.now(ZoneInfo("America/New_York"))
        # Weekdays only (Mon=0 .. Fri=4)
        if et_now.weekday() > 4:
            return False
        from backend.config import MARKET_OPEN_TIME, MARKET_CLOSE_TIME
        return MARKET_OPEN_TIME <= et_now.time() <= MARKET_CLOSE_TIME

    def get_price_snapshots(self, symbols: List[str]) -> Dict:
        """
        Get rich snapshot data for the /stocks/prices endpoint.

        Returns a dict of symbol -> {
            price, daily_close, previous_close, change, changePercent,
            extended_price, extended_change, extended_change_percent,
            open_price, high_price, low_price, volume, timestamp
        }
        """
        if not self.is_available:
            return {}

        try:
            snapshots = self._get_snapshots(symbols)
        except Exception as e:
            logger.error(f"Error fetching snapshots for prices: {e}")
            return {}

        market_open = self._is_market_open()

        result = {}
        for symbol in symbols:
            snapshot = snapshots.get(symbol)
            if not snapshot:
                continue

            daily_bar = getattr(snapshot, 'daily_bar', None)
            prev_daily_bar = getattr(snapshot, 'previous_daily_bar', None)
            latest_trade = getattr(snapshot, 'latest_trade', None)

            if not daily_bar:
                continue

            try:
                daily_close = float(daily_bar.close)
                open_price = float(daily_bar.open)
                high_price = float(daily_bar.high)
                low_price = float(daily_bar.low)
                volume = int(daily_bar.volume)

                previous_close = (
                    float(prev_daily_bar.close)
                    if prev_daily_bar else None
                )

                # Latest trade price (includes extended hours)
                latest_price = (
                    float(latest_trade.price)
                    if latest_trade else daily_close
                )

                # Regular market change (daily close vs previous close)
                change = 0.0
                change_percent = 0.0
                if previous_close and previous_close > 0:
                    change = round(daily_close - previous_close, 2)
                    change_percent = round(
                        ((daily_close - previous_close) / previous_close)
                        * 100, 2
                    )

                # Extended hours change (latest trade vs daily close)
                # Always show when market is closed; during market hours
                # the "extended" concept doesn't apply.
                extended_change = None
                extended_change_percent = None
                if not market_open and daily_close > 0:
                    diff = latest_price - daily_close
                    extended_change = round(diff, 2)
                    extended_change_percent = round(
                        (diff / daily_close) * 100, 2
                    )

                result[symbol] = {
                    "price": round(latest_price, 2),
                    "daily_close": round(daily_close, 2),
                    "previous_close": (
                        round(previous_close, 2) if previous_close else None
                    ),
                    "change": change,
                    "changePercent": change_percent,
                    "extended_change": extended_change,
                    "extended_change_percent": extended_change_percent,
                    "open_price": round(open_price, 2),
                    "high_price": round(high_price, 2),
                    "low_price": round(low_price, 2),
                    "volume": volume,
                    "timestamp": (
                        str(latest_trade.timestamp)
                        if latest_trade else None
                    ),
                }
            except Exception as e:
                logger.warning(
                    f"Error processing snapshot for {symbol}: {e}"
                )

        return result

    def _get_latest_quotes(self, symbols: List[str]) -> Dict:
        """Fetch latest quotes for multiple symbols."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes = self.client.get_stock_latest_quote(request)
            return quotes
        except Exception as e:
            logger.warning(f"Error fetching latest quotes: {e}")
            return {}

    def _get_latest_bars(self, symbols: List[str]) -> Dict:
        """Fetch latest bars (OHLCV) for multiple symbols."""
        try:
            request = StockLatestBarRequest(symbol_or_symbols=symbols)
            bars = self.client.get_stock_latest_bar(request)
            return bars
        except Exception as e:
            logger.warning(f"Error fetching latest bars: {e}")
            return {}

    def _get_previous_day_bars(self, symbols: List[str]) -> Dict:
        """Fetch previous trading day's bar data for change calculation."""
        try:
            # Get data from 5 days ago to yesterday
            end = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            start = end - timedelta(days=5)

            request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Day,
                start=start,
                end=end
            )
            bars = self.client.get_stock_bars(request)

            # Get the most recent bar for each symbol (previous trading day)
            result = {}
            for symbol in symbols:
                if symbol in bars:
                    symbol_bars = bars[symbol]
                    if symbol_bars:
                        # Get the last bar (most recent)
                        result[symbol] = symbol_bars[-1]

            return result
        except Exception as e:
            logger.warning(f"Error fetching previous day bars: {e}")
            return {}

    def _build_technical_data(
        self,
        symbol: str,
        quote: Optional[object],
        bar: Optional[object],
        prev_bar: Optional[object]
    ) -> Optional[TechnicalData]:
        """
        Build TechnicalData object from Alpaca quote and bar data.

        Args:
            symbol: Stock ticker symbol
            quote: Latest quote data (bid/ask)
            bar: Latest bar data (OHLCV)
            prev_bar: Previous trading day's bar

        Returns:
            TechnicalData object or None if insufficient data
        """
        if not bar:
            logger.debug(f"No bar data for {symbol}")
            return None

        try:
            # Extract bar data (OHLCV)
            open_price = float(bar.open)
            high_price = float(bar.high)
            low_price = float(bar.low)
            close_price = float(bar.close)
            volume = int(bar.volume)

            # Calculate previous close and change percent
            previous_close = None
            change_percent = None
            if prev_bar:
                previous_close = float(prev_bar.close)
                if previous_close > 0:
                    change_percent = (
                        (close_price - previous_close) / previous_close
                    ) * 100
            # Calculate simple support/resistance levels
            support_level = low_price * 0.98
            resistance_level = high_price * 1.02

            # Calculate simple volatility (high-low as % of close)
            volatility = None
            if close_price > 0:
                volatility = ((high_price - low_price) / close_price) * 100

            return TechnicalData(
                symbol=symbol,
                timestamp=datetime.utcnow(),
                open_price=round(open_price, 2),
                high_price=round(high_price, 2),
                low_price=round(low_price, 2),
                close_price=round(close_price, 2),
                volume=volume,
                previous_close=(
                    round(previous_close, 2) if previous_close else None
                ),
                change_percent=(
                    round(change_percent, 2) if change_percent else None
                ),
                support_level=round(support_level, 2),
                resistance_level=round(resistance_level, 2),
                volatility=round(volatility, 2) if volatility else None
            )
        except Exception as e:
            logger.warning(f"Error building TechnicalData for {symbol}: {e}")
            return None

    def get_quote_price(self, symbol: str) -> Optional[float]:
        """
        Get the latest quote price for a single symbol.

        Useful for quick price lookups.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Latest price (mid-point of bid/ask) or None
        """
        if not self.is_available:
            return None

        try:
            quotes = self._get_latest_quotes([symbol])
            if symbol in quotes:
                quote = quotes[symbol]
                # Return mid-point of bid/ask
                bid = float(quote.bid_price) if quote.bid_price else 0
                ask = float(quote.ask_price) if quote.ask_price else 0
                if bid > 0 and ask > 0:
                    return round((bid + ask) / 2, 2)
                return ask or bid or None
        except Exception as e:
            logger.warning(f"Error getting quote for {symbol}: {e}")

        return None
