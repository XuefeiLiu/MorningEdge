"""
Save operations for news_articles table.
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from hashlib import md5
from supabase import Client

from backend.models import NewsItem
from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _string_id_to_bigint(string_id: str) -> int:
    """
    Convert a string ID to a bigint by hashing it.
    
    Args:
        string_id: String ID (e.g., "av_a6af5309e89a")
        
    Returns:
        Integer hash of the string ID (bigint)
    """
    # Use MD5 hash and take first 15 digits to fit in bigint range
    # PostgreSQL bigint is -9223372036854775808 to 9223372036854775807
    hash_bytes = md5(string_id.encode('utf-8')).digest()
    # Convert to positive integer (use first 7 bytes = 14 hex digits = fits in bigint)
    bigint_id = int.from_bytes(hash_bytes[:7], byteorder='big', signed=False)
    # Ensure it's within PostgreSQL bigint range (use modulo to be safe)
    max_bigint = 9223372036854775807
    return bigint_id % max_bigint


def convert_to_db_format(news_item: NewsItem, ticker: str = None) -> Dict[str, Any]:
    """
    Convert NewsItem to database format.
    
    Args:
        news_item: NewsItem object
        ticker: Stock ticker (optional, uses news_item.ticker if not provided)
        
    Returns:
        Dict with database column names as keys
    """
    # Use ticker from news_item, or provided ticker as fallback
    db_ticker = news_item.ticker
    # Convert published_at to timezone-aware if needed
    published_at = news_item.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    
    # Convert created_at to timezone-aware if needed
    created_at = news_item.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    
    # Serialize NewsItem to JSON for raw field (url is NOT NULL in DB, use "" when missing)
    db_data = {
        "id": news_item.id,
        "ticker": db_ticker,
        "published_at": published_at,
        "title": news_item.title,
        "summary": news_item.summary,
        "url": news_item.url if news_item.url is not None else "",
        "source": news_item.source,
        "created_at": created_at,
        "collector": news_item.collector,
    }
    
    # Include embedding if present (for summary embeddings)
    if news_item.embedding is not None:
        db_data["embedding"] = news_item.embedding
    
    return db_data


def save_articles(
    supabase: Client,
    ticker: str,
    items: List[Dict[str, Any]],
    source: str = None,
    start_date: datetime = None,
    end_date: datetime = None
) -> int:
    """
    Save news articles to database.
    
    Args:
        supabase: Supabase client instance
        ticker: Stock ticker (for logging)
        items: List of dicts in database format (from convert_to_db_format)
        source: Source/collector name (for logging)
        start_date: Start date of the collection window (for logging)
        end_date: End date of the collection window (for logging)
        
    Returns:
        Number of articles inserted
    """
    if not items:
        return 0
    
    if not supabase:
        supabase = get_supabase_client()
    
    # Format date range for logging
    date_range_str = ""
    if start_date and end_date:
        start_str = start_date.strftime("%Y-%m-%d") if isinstance(start_date, datetime) else str(start_date)
        end_str = end_date.strftime("%Y-%m-%d") if isinstance(end_date, datetime) else str(end_date)
        date_range_str = f" ({start_str} to {end_str})"
    elif start_date:
        start_str = start_date.strftime("%Y-%m-%d") if isinstance(start_date, datetime) else str(start_date)
        date_range_str = f" (from {start_str})"
    elif end_date:
        end_str = end_date.strftime("%Y-%m-%d") if isinstance(end_date, datetime) else str(end_date)
        date_range_str = f" (until {end_str})"
    
    source_str = f" from {source}" if source else ""
    
    inserted = 0
    for item in items:
        try:
            # Convert string ID to bigint for database
            string_id = item["id"]
            db_id = _string_id_to_bigint(string_id)
            
            # Prepare data for Supabase - match NewsItem model fields (url is NOT NULL in DB)
            article_data = {
                "id": db_id,
                "ticker": item["ticker"],
                "published_at": item["published_at"].isoformat() if isinstance(item["published_at"], datetime) else item["published_at"],
                "title": item["title"],
                "summary": item.get("summary"),
                "url": item.get("url") or "",
                "source": item.get("source"),
                "created_at": item.get("created_at").isoformat() if isinstance(item.get("created_at"), datetime) else item.get("created_at"),
                "collector": item.get("collector"),
            }
            
            # Include embedding if present (pgvector accepts list format)
            if "embedding" in item and item["embedding"] is not None:
                # Convert to list if it's a numpy array or already a list
                embedding = item["embedding"]
                if hasattr(embedding, 'tolist'):
                    # numpy array - convert to list
                    article_data["embedding"] = embedding.tolist()
                elif isinstance(embedding, list):
                    # Already a list - use as-is
                    article_data["embedding"] = embedding
                else:
                    logger.warning(f"Unexpected embedding type for article {item.get('id')}: {type(embedding)}, skipping embedding")
            
            # Try to insert - Supabase will handle conflicts based on unique constraints
            # If URL exists, conflict is on (ticker, url)
            # Otherwise, conflict is on (ticker, published_at, title)
            result = supabase.table("news_articles").insert(article_data).execute()

            if result.data:
                inserted += 1
                try:
                    from backend.storage.elasticsearch_sync import index_news_article
                    index_news_article(article_data)
                except Exception:
                    pass
        except Exception as e:
            # Supabase returns error for conflicts, which is expected for duplicates
            error_msg = str(e).lower()
            if "duplicate" in error_msg or "unique" in error_msg or "conflict" in error_msg:
                # This is a duplicate, skip it
                continue
            else:
                logger.error(f"Error inserting article for {ticker}{source_str}: {e}")
                continue
    
    logger.info(f"Inserted {inserted} new articles for {ticker}{source_str}{date_range_str} (skipped {len(items) - inserted} duplicates)")
    return inserted
