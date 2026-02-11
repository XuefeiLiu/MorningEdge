"""Briefing generation and AI summary endpoints."""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.models import (
    AISummaryRequest, AISummaryResponse, BriefingReport,
)
from backend.storage.watchlist_manager import watchlist_manager
from backend.services.briefing import briefing_generator
from backend.services.ai_summaries import ai_summary_generator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/briefing", response_model=BriefingReport, tags=["Briefing"])
async def get_briefing(
    start_time: Optional[datetime] = Query(None, description="Start of data collection window"),
    end_time: Optional[datetime] = Query(None, description="End of data collection window"),
    use_mock: bool = Query(False, description="Force use of mock data")
):
    """Generate a pre-market briefing report for the current watchlist."""
    symbols = watchlist_manager.get_symbols()
    if not symbols:
        raise HTTPException(status_code=400, detail="Watchlist is empty. Add symbols first.")
    try:
        report = await briefing_generator.generate(
            symbols=symbols, start_time=start_time, end_time=end_time, use_mock=use_mock
        )
        return report
    except asyncio.CancelledError as ce:
        logger.error(f"Request was cancelled: {ce}")
        raise HTTPException(status_code=499, detail="Request was cancelled by client")
    except Exception as e:
        logger.error(f"Error generating briefing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate briefing: {str(e)}")


@router.get("/briefing/stock/{symbol}", tags=["Briefing"])
async def get_stock_briefing(
    symbol: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    use_mock: bool = False
):
    """Generate a briefing report for a single stock."""
    try:
        report = await briefing_generator.generate(
            symbols=[symbol.upper()], start_time=start_time, end_time=end_time, use_mock=use_mock
        )
        if report.stock_summaries:
            return {
                "symbol": symbol.upper(),
                "summary": report.stock_summaries[0],
                "news": [n for n in report.company_news if symbol.upper() == n.ticker.upper()],
                "filings": [f for f in report.sec_filings if f.symbol == symbol.upper()],
                "macro_events": report.macro_events,
                "risk_warnings": report.risk_warnings
            }
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating stock briefing for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate briefing: {str(e)}")


@router.post("/ai/summarize", response_model=AISummaryResponse, tags=["AI"])
async def generate_ai_summary(request: AISummaryRequest):
    """Generate an AI-powered summary of provided items."""
    try:
        response = await ai_summary_generator.summarize_items(items=request.items, context="market data")
        return response
    except Exception as e:
        logger.error(f"Error generating AI summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")


@router.get("/ai/briefing-summary", response_model=AISummaryResponse, tags=["AI"])
async def get_briefing_ai_summary(
    focus_symbols: Optional[str] = Query(None, description="Comma-separated list of symbols to focus on")
):
    """Generate an AI-powered summary of the current briefing."""
    symbols = watchlist_manager.get_symbols()
    if not symbols:
        raise HTTPException(status_code=400, detail="Watchlist is empty. Add symbols first.")
    focus = None
    if focus_symbols:
        focus = [s.strip().upper() for s in focus_symbols.split(",")]
    try:
        report = await briefing_generator.generate(symbols=symbols)
        response = await ai_summary_generator.summarize_briefing(
            news=report.company_news, macro=report.macro_events,
            filings=report.sec_filings, stock_summaries=report.stock_summaries,
            focus_symbols=focus
        )
        return response
    except Exception as e:
        logger.error(f"Error generating AI briefing summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")
