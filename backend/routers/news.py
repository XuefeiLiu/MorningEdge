"""News endpoints: stock news and macro news."""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.models import StockNewsItem, MacroNewsItem

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/news/stock", response_model=List[StockNewsItem], tags=["News"])
async def get_stock_news(
    ticker: str = Query(..., description="Stock ticker symbol"),
    start_date: Optional[datetime] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[datetime] = Query(None, description="End date (inclusive)"),
    limit: int = Query(100, description="Maximum number of results", ge=1, le=1000)
):
    """Get stock news articles for a specific ticker."""
    from backend.storage.news_articles_query import get_articles
    from backend.storage.supabase_client import get_supabase_client
    try:
        supabase = get_supabase_client()
        articles = get_articles(supabase=supabase, ticker=ticker.upper().strip(), start_date=start_date, end_date=end_date, limit=limit)
        return [
            StockNewsItem(
                id=a.get("id"), ticker=a.get("ticker", ""), title=a.get("title", ""),
                summary=a.get("summary"), url=a.get("url"), source=a.get("source", "Unknown"),
                published_at=a.get("published_at")
            )
            for a in articles
        ]
    except Exception as e:
        logger.error("Error fetching stock news: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/news/macro", response_model=List[MacroNewsItem], tags=["News"])
async def get_macro_news(
    ticker: Optional[str] = Query(None, description="Filter by related tickers"),
    start_date: Optional[datetime] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[datetime] = Query(None, description="End date (inclusive)"),
    limit: int = Query(100, description="Maximum number of results", ge=1, le=1000)
):
    """Get macro economic news articles."""
    from backend.storage.macro_articles_query import get_macro_articles
    from backend.storage.supabase_client import get_supabase_client
    try:
        supabase = get_supabase_client()
        articles = get_macro_articles(supabase=supabase, collector="alpha_vantage", ticker=ticker, start_date=start_date, end_date=end_date, limit=limit)
        return [
            MacroNewsItem(
                id=a.get("id"), title=a.get("title", ""), summary=a.get("summary"),
                url=a.get("url"), source=a.get("source", "Unknown"), published_at=a.get("published_at"),
                primary_topic=a.get("primary_topic"), related_tickers=a.get("related_tickers")
            )
            for a in articles
        ]
    except Exception as e:
        logger.error("Error fetching macro news: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
