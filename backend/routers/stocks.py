"""Stocks and prices endpoints: NASDAQ 100, real-time prices, historical bars, 5-min prices."""
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.models import (
    StockInfo, StockPriceInfo, CandlestickBar, HistoricalBarsResponse, Price5MinItem,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stocks/nasdaq100", response_model=List[StockInfo], tags=["Stocks"])
async def get_nasdaq100_stocks():
    """Get NASDAQ 100 stock list with company names and exchange."""
    from backend.storage.nasdaq100_tickers import get_nasdaq100_stocks
    try:
        stocks = get_nasdaq100_stocks(use_api=False)
        return [StockInfo(ticker=s["ticker"], name=s["name"], exchange=s.get("exchange", "NASDAQ")) for s in stocks]
    except Exception as e:
        logger.error(f"Error fetching NASDAQ 100 stocks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch NASDAQ 100 stocks: {str(e)}")


@router.get("/stocks/prices", response_model=List[StockPriceInfo], tags=["Stocks"])
async def get_stock_prices(symbols: str = Query(..., description="Comma-separated stock symbols")):
    """Get real-time stock prices from Alpaca market data."""
    from backend.services.collectors.alpaca_market import AlpacaMarketDataCollector
    from backend.storage.nasdaq100_tickers import get_nasdaq100_stocks
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="No symbols provided")
    nasdaq_stocks = get_nasdaq100_stocks(use_api=False)
    name_map = {s["ticker"]: s["name"] for s in nasdaq_stocks}
    try:
        collector = AlpacaMarketDataCollector()
        if collector.is_available:
            snapshots = collector.get_price_snapshots(symbol_list)
            result = []
            for sym in symbol_list:
                snap = snapshots.get(sym)
                if snap:
                    result.append(StockPriceInfo(
                        symbol=sym, name=name_map.get(sym, sym),
                        price=snap["price"], change=snap["change"], changePercent=snap["changePercent"],
                        open_price=snap.get("open_price"), high_price=snap.get("high_price"),
                        low_price=snap.get("low_price"), volume=snap.get("volume"),
                        extendedChange=snap.get("extended_change"),
                        extendedChangePercent=snap.get("extended_change_percent"),
                    ))
                else:
                    result.append(StockPriceInfo(symbol=sym, name=name_map.get(sym, sym), price=0, change=0, changePercent=0))
            logger.info(f"Returned prices for {len(result)} symbols from Alpaca")
            return result
        else:
            logger.warning(f"Alpaca unavailable: {collector.get_last_error()}")
    except Exception as e:
        logger.error(f"Error fetching stock prices from Alpaca: {e}")
    return [StockPriceInfo(symbol=sym, name=name_map.get(sym, sym), price=0, change=0, changePercent=0) for sym in symbol_list]


@router.get("/stocks/bars", response_model=HistoricalBarsResponse, tags=["Stocks"])
async def get_stock_bars(
    symbol: str = Query(..., description="Stock ticker symbol"),
    timeframe: str = Query("1Day", description="Timeframe: 1Min, 5Min, 15Min, 1Hour, 1Day"),
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    end_ts: Optional[int] = Query(None, description="End timestamp (Unix seconds)"),
    start_ts: Optional[int] = Query(None, description="Start timestamp (Unix seconds)")
):
    """Get historical OHLCV bar data for TradingView-style charts."""
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        try:
            from alpaca.data.enums import DataFeed
        except ImportError:
            DataFeed = None  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="alpaca-py library not installed")

    api_key = os.getenv("alpaca-api-key", "").strip().strip("'\"")
    secret_key = os.getenv("alpaca-secret-key", "").strip().strip("'\"")
    if not api_key or not secret_key:
        raise HTTPException(status_code=503, detail="Alpaca API keys not configured")

    timeframe_map = {
        "1Min": TimeFrame.Minute, "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute), "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame.Hour, "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
        "1Day": TimeFrame.Day, "1Week": TimeFrame.Week,
    }
    tf = timeframe_map.get(timeframe, TimeFrame.Day)

    try:
        client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
        is_intraday = timeframe in ("1Min", "5Min", "15Min", "30Min", "1Hour", "4Hour")

        if end_ts is not None:
            end = datetime.utcfromtimestamp(end_ts)
            start = datetime.utcfromtimestamp(start_ts) if start_ts is not None else end - timedelta(days=days)
        elif is_intraday:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("America/New_York")
            utc = ZoneInfo("UTC")
            now_et = datetime.now(et)
            if now_et.weekday() < 5:
                end = datetime.utcnow()
                start = end - timedelta(days=days)
            else:
                days_since_friday = now_et.weekday() - 4
                last_fri_et = now_et - timedelta(days=days_since_friday)
                end_et = last_fri_et.replace(hour=20, minute=0, second=0, microsecond=0)
                start_et = (end_et - timedelta(days=max(days - 1, 0))).replace(hour=4, minute=0, second=0, microsecond=0)
                start = start_et.astimezone(utc).replace(tzinfo=None)
                end = end_et.astimezone(utc).replace(tzinfo=None)
        else:
            end = datetime.utcnow()
            start = end - timedelta(days=days)

        feed = None
        if DataFeed is not None:
            feed_pref = (os.getenv("ALPACA_BARS_FEED") or "iex").strip().lower()
            feed = DataFeed.SIP if feed_pref == "sip" else DataFeed.IEX

        request_kw: dict = {"symbol_or_symbols": [symbol.upper()], "timeframe": tf, "start": start, "end": end}
        if feed is not None:
            request_kw["feed"] = feed
        bars_request = StockBarsRequest(**request_kw)

        try:
            bars_response = client.get_stock_bars(bars_request)
        except Exception as bars_err:
            err_msg = str(bars_err).lower()
            if "sip" in err_msg and "subscription" in err_msg and DataFeed is not None and feed != DataFeed.IEX:
                logger.warning("Bars request failed (likely SIP not allowed), retrying with IEX feed: %s", bars_err)
                request_kw["feed"] = DataFeed.IEX
                bars_response = client.get_stock_bars(StockBarsRequest(**request_kw))
            else:
                raise

        symbol_upper = symbol.upper()
        bar_list = []
        try:
            if hasattr(bars_response, 'data') and bars_response.data:
                data = bars_response.data
                if symbol_upper in data:
                    bar_list = list(data[symbol_upper])
            if not bar_list:
                try:
                    bar_list = list(bars_response[symbol_upper])
                except (KeyError, TypeError):
                    pass
            if not bar_list and hasattr(bars_response, 'get'):
                result = bars_response.get(symbol_upper)
                if result:
                    bar_list = list(result)
        except Exception as ex:
            logger.warning(f"Error extracting bars: {ex}")

        if not bar_list:
            return HistoricalBarsResponse(symbol=symbol_upper, bars=[], timeframe=timeframe)

        bars = []
        for bar in bar_list:
            ts = bar.timestamp
            unix_ts = int(ts.timestamp()) if hasattr(ts, 'timestamp') else int(ts)
            bars.append(CandlestickBar(
                time=str(unix_ts), open=float(bar.open), high=float(bar.high),
                low=float(bar.low), close=float(bar.close),
                volume=int(bar.volume) if bar.volume else None
            ))
        logger.info(f"Returned {len(bars)} bars for {symbol_upper}")
        return HistoricalBarsResponse(symbol=symbol_upper, bars=bars, timeframe=timeframe)
    except Exception as e:
        logger.error(f"Error fetching bars for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch bar data: {str(e)}")


@router.get("/prices/5min", response_model=List[Price5MinItem], tags=["Prices"])
async def get_5min_prices(
    ticker: str = Query(..., description="Stock ticker symbol"),
    start_date: Optional[datetime] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[datetime] = Query(None, description="End date (inclusive)"),
    limit: int = Query(10000, description="Maximum number of results", ge=1, le=50000)
):
    """Get 5-minute intraday price data for a ticker."""
    from backend.storage.stock_prices_5min_query import get_prices_by_ticker
    from backend.storage.supabase_client import get_supabase_client
    try:
        supabase = get_supabase_client()
        prices = get_prices_by_ticker(supabase=supabase, ticker=ticker.upper().strip(), start_date=start_date, end_date=end_date, limit=limit)
        result = [
            Price5MinItem(
                timestamp=p.get("timestamp"), open=float(p.get("open", 0)),
                high=float(p.get("high", 0)), low=float(p.get("low", 0)),
                close=float(p.get("close", 0)), volume=int(p.get("volume", 0))
            )
            for p in prices
        ]
        result.sort(key=lambda x: x.timestamp)
        return result
    except Exception as e:
        logger.error(f"Error fetching 5min prices for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch 5min prices: {str(e)}")
