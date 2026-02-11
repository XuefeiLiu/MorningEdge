"""
External API fetch operations for news articles.
These functions fetch news from external APIs (not from database).
"""
import asyncio
import logging
import httpx
from typing import List
from datetime import datetime, timezone
from supabase import Client

from backend.models import NewsItem
from backend.services.collectors.financial_datasets import FinancialDatasetsCollector
from backend.services.collectors.alpha_vantage import AlphaVantageCollector
from backend.services.collectors.massive import MassiveCollector
from backend.services.collectors.marketaux import MarketauxCollector
from backend.services.collectors.openai import OpenAICollector
from backend.services.collectors.gemini import GeminiCollector
from backend.config import (
    FINANCIAL_DATASETS_API_KEY, 
    ALPHA_VANTAGE_API_KEY, 
    MASSIVE_API_KEY,
    MARKETAUX_API_KEY,
    OPENAI_API_KEY,
    GEMINI_API_KEY
)

logger = logging.getLogger(__name__)

# Initialize collectors at module level
_fd_collector = FinancialDatasetsCollector(api_key=FINANCIAL_DATASETS_API_KEY)
_av_collector = AlphaVantageCollector()
_massive_collector = MassiveCollector(api_key=MASSIVE_API_KEY)
_marketaux_collector = MarketauxCollector(api_key=MARKETAUX_API_KEY)
_openai_collector = OpenAICollector(api_key=OPENAI_API_KEY)
_gemini_collector = GeminiCollector(api_key=GEMINI_API_KEY)


async def fetch_news_financial_datasets(ticker: str, day: datetime) -> List[NewsItem]:
    """
    Fetch news from Financial Datasets API for one day.
    
    Args:
        ticker: Stock ticker symbol
        day: Date to fetch news for (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _fd_collector.is_available:
        logger.warning(f"Financial Datasets collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the day
    start_time = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = day.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        news_items = await _fd_collector.collect(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from Financial Datasets for {ticker}")
        return news_items
    except Exception as e:
        logger.error(f"Error fetching Financial Datasets news for {ticker}: {e}")
        return []


async def fetch_news_alpha_vantage(ticker: str, day: datetime) -> List[NewsItem]:
    """
    Fetch news from Alpha Vantage API for one day.
    
    Args:
        ticker: Stock ticker symbol
        day: Date to fetch news for (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _av_collector.is_available:
        logger.warning(f"Alpha Vantage collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the day
    start_time = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = day.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        news_items = await _av_collector.collect_news(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from Alpha Vantage for {ticker}")
        return news_items
    except Exception as e:
        logger.error(f"Error fetching Alpha Vantage news for {ticker}: {e}")
        return []


async def fetch_news_alpha_vantage_range(
    ticker: str, 
    start_date: datetime, 
    end_date: datetime
) -> List[NewsItem]:
    """
    Fetch news from Alpha Vantage API for a date range.
    
    Args:
        ticker: Stock ticker symbol
        start_date: Start date (datetime object)
        end_date: End date (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _av_collector.is_available:
        logger.warning(f"Alpha Vantage collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the range
    start_time = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        news_items = await _av_collector.collect_news(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from Alpha Vantage for {ticker} ({start_date.date()} to {end_date.date()})")
        return news_items
    except Exception as e:
        logger.error(f"Error fetching Alpha Vantage news for {ticker}: {e}")
        return []


async def fetch_news_financial_datasets_range(
    ticker: str, 
    start_date: datetime, 
    end_date: datetime
) -> List[NewsItem]:
    """
    Fetch news from Financial Datasets API for a date range.
    
    Args:
        ticker: Stock ticker symbol
        start_date: Start date (datetime object)
        end_date: End date (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _fd_collector.is_available:
        logger.warning(f"Financial Datasets collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the range
    start_time = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        news_items = await _fd_collector.collect(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from Financial Datasets for {ticker} ({start_date.date()} to {end_date.date()})")
        return news_items
    except Exception as e:
        logger.error(f"Error fetching Financial Datasets news for {ticker}: {e}")
        return []


async def fetch_news_massive_range(
    ticker: str, 
    start_date: datetime, 
    end_date: datetime
) -> List[NewsItem]:
    """
    Fetch news from Massive API for a date range.
    
    Args:
        ticker: Stock ticker symbol
        start_date: Start date (datetime object)
        end_date: End date (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _massive_collector.is_available:
        logger.warning(f"Massive collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the range
    start_time = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        logger.debug(f"Calling Massive API for {ticker} ({start_date.date()} to {end_date.date()})...")
        news_items = await _massive_collector.collect(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from Massive for {ticker} ({start_date.date()} to {end_date.date()})")
        return news_items
    except asyncio.TimeoutError as e:
        logger.error(f"Timeout fetching Massive news for {ticker}: {e}")
        return []
    except httpx.TimeoutException as e:
        logger.error(f"HTTP timeout fetching Massive news for {ticker}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching Massive news for {ticker}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return []


async def fetch_news_marketaux_range(
    ticker: str, 
    start_date: datetime, 
    end_date: datetime
) -> List[NewsItem]:
    """
    Fetch news from Marketaux API for a date range.
    
    Args:
        ticker: Stock ticker symbol
        start_date: Start date (datetime object)
        end_date: End date (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _marketaux_collector.is_available:
        logger.warning(f"Marketaux collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the range
    start_time = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        news_items = await _marketaux_collector.collect(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from Marketaux for {ticker} ({start_date.date()} to {end_date.date()})")
        return news_items
    except Exception as e:
        logger.error(f"Error fetching Marketaux news for {ticker}: {e}")
        return []


async def fetch_news_openai_range(
    ticker: str, 
    start_date: datetime, 
    end_date: datetime
) -> List[NewsItem]:
    """
    Fetch news from OpenAI API for a date range.
    
    Args:
        ticker: Stock ticker symbol
        start_date: Start date (datetime object)
        end_date: End date (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _openai_collector.is_available:
        logger.warning(f"OpenAI collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the range
    start_time = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        news_items = await _openai_collector.collect(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from OpenAI for {ticker} ({start_date.date()} to {end_date.date()})")
        return news_items
    except Exception as e:
        logger.error(f"Error fetching OpenAI news for {ticker}: {e}")
        return []


async def fetch_news_gemini_range(ticker: str, start_date: datetime, end_date: datetime) -> List[NewsItem]:
    """
    Fetch news from Gemini API for a date range.
    
    Args:
        ticker: Stock ticker symbol
        start_date: Start date (datetime object)
        end_date: End date (datetime object)
        
    Returns:
        List of NewsItem objects
    """
    if not _gemini_collector.is_available:
        logger.warning(f"Gemini collector unavailable for {ticker}")
        return []
    
    # Create start and end time for the range
    start_time = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Ensure timezone-aware
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    
    try:
        news_items = await _gemini_collector.collect(
            symbols=[ticker],
            start_time=start_time,
            end_time=end_time
        )
        logger.info(f"Fetched {len(news_items)} news items from Gemini for {ticker} ({start_date.date()} to {end_date.date()})")
        return news_items
    except Exception as e:
        logger.error(f"Error fetching Gemini news for {ticker}: {e}")
        return []
