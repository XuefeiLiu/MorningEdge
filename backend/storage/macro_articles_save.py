"""
Save operations for macro_articles table.
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from hashlib import md5
from supabase import Client

from backend.storage.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


def _string_id_to_bigint(string_id: str) -> int:
    """
    Convert a string ID to a bigint by hashing it.
    
    Args:
        string_id: String ID (e.g., "av_macro_a6af5309e89a")
        
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


def convert_to_db_format(
    article_data: Dict[str, Any],
    collector: str
) -> Dict[str, Any]:
    """
    Convert article data to database format for macro_articles table.
    
    Args:
        article_data: Dict with article fields:
            - id: String ID (will be converted to bigint)
            - title: Article title (required)
            - summary: Article summary (optional)
            - url: Article URL (optional)
            - source: News source name (required)
            - published_at: Publication datetime (required)
            - related_tickers: List of ticker symbols (optional)
            - embedding: Vector embedding (optional)
        collector: Collector name (default: "alpha_vantage")
        
    Returns:
        Dict with database column names as keys
    """
    # Convert published_at to timezone-aware if needed
    published_at = article_data.get("published_at")
    if isinstance(published_at, str):
        # Try to parse ISO format
        try:
            published_at = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        except ValueError:
            logger.warning(f"Could not parse published_at: {published_at}")
            published_at = datetime.now(timezone.utc)
    elif published_at is None:
        published_at = datetime.now(timezone.utc)
    
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    
    # Get created_at (use current time if not provided)
    created_at = article_data.get("created_at")
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    elif isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except ValueError:
            created_at = datetime.now(timezone.utc)
    
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    
    # Prepare database data
    db_data = {
        "id": article_data["id"],  # Will be converted to bigint in save_articles
        "title": article_data["title"],
        "summary": article_data.get("summary"),
        "url": article_data.get("url"),
        "source": article_data.get("source", "Unknown"),
        # Temporarily disabled fields:
        # "source_domain": article_data.get("source_domain"),
        # "category_within_source": article_data.get("category_within_source"),
        "published_at": published_at,
        "created_at": created_at,
        "collector": collector,  # Collector name (e.g., "alpha_vantage")
    }
    
    # Temporarily disabled: Handle authors (store as JSONB array)
    # authors = article_data.get("authors")
    # if authors:
    #     if isinstance(authors, list):
    #         db_data["authors"] = [str(a).strip() for a in authors if a]
    #     elif isinstance(authors, str):
    #         db_data["authors"] = [authors.strip()]
    
    # Temporarily disabled: Handle banner_image
    # if article_data.get("banner_image"):
    #     db_data["banner_image"] = article_data.get("banner_image")
    
    # Handle related_tickers (extract from ticker_sentiment or use provided list)
    related_tickers = article_data.get("related_tickers")
    if not related_tickers and article_data.get("ticker_sentiment"):
        # Extract from ticker_sentiment array
        ticker_sentiment = article_data.get("ticker_sentiment", [])
        related_tickers = [item.get("ticker", "").upper().strip() for item in ticker_sentiment if item.get("ticker")]
        related_tickers = [t for t in related_tickers if t]
    
    if related_tickers:
        if isinstance(related_tickers, list):
            # Ensure all tickers are uppercase strings
            related_tickers = [str(t).upper().strip() for t in related_tickers if t]
            db_data["related_tickers"] = related_tickers
        elif isinstance(related_tickers, str):
            # Try to parse JSON string
            try:
                parsed = json.loads(related_tickers)
                if isinstance(parsed, list):
                    db_data["related_tickers"] = [str(t).upper().strip() for t in parsed if t]
            except json.JSONDecodeError:
                logger.warning(f"Could not parse related_tickers JSON: {related_tickers}")
    
    # Handle topics (store as JSONB array of objects)
    topics = article_data.get("topics")
    if topics:
        if isinstance(topics, list):
            # Store as list of topic objects
            db_data["topics"] = topics
        elif isinstance(topics, str):
            try:
                parsed = json.loads(topics)
                if isinstance(parsed, list):
                    db_data["topics"] = parsed
            except json.JSONDecodeError:
                logger.warning(f"Could not parse topics JSON: {topics}")
    
    # Handle primary_topic (the topic with highest relevance_score)
    primary_topic = article_data.get("primary_topic")
    if primary_topic:
        db_data["primary_topic"] = str(primary_topic).strip()
    else:
        # If primary_topic is not set, try to extract it from topics
        # This is a fallback in case primary_topic wasn't set during filtering
        topics = article_data.get("topics", [])
        if topics and isinstance(topics, list):
            max_relevance = -1.0
            max_relevance_topic = None
            for topic_item in topics:
                if isinstance(topic_item, dict):
                    topic_name = topic_item.get("topic", "")
                    relevance_score_str = topic_item.get("relevance_score", "0")
                    try:
                        relevance_score = float(relevance_score_str)
                        if relevance_score > max_relevance:
                            max_relevance = relevance_score
                            max_relevance_topic = topic_name
                    except (ValueError, TypeError):
                        continue
            if max_relevance_topic:
                db_data["primary_topic"] = str(max_relevance_topic).strip()
                logger.info(f"Extracted primary_topic '{max_relevance_topic}' from topics for article '{article_data.get('title', 'N/A')[:50]}'")
            else:
                logger.warning(f"Article '{article_data.get('title', 'N/A')[:50]}' has no primary_topic and could not extract from topics")
        else:
            logger.warning(f"Article '{article_data.get('title', 'N/A')[:50]}' has no primary_topic and no topics to extract from")
    
    # Handle sentiment scores
    if article_data.get("overall_sentiment_score") is not None:
        db_data["overall_sentiment_score"] = float(article_data.get("overall_sentiment_score"))
    if article_data.get("overall_sentiment_label"):
        db_data["overall_sentiment_label"] = article_data.get("overall_sentiment_label")
    
    # Include embedding if present (pgvector accepts list format)
    if "embedding" in article_data and article_data["embedding"] is not None:
        embedding = article_data["embedding"]
        if hasattr(embedding, 'tolist'):
            # numpy array - convert to list
            db_data["embedding"] = embedding.tolist()
        elif isinstance(embedding, list):
            # Already a list - use as-is
            db_data["embedding"] = embedding
        else:
            logger.warning(f"Unexpected embedding type: {type(embedding)}, skipping embedding")
    
    return db_data


def save_articles(
    supabase: Client,
    items: List[Dict[str, Any]],
    collector: str,
    start_date: datetime = None,
    end_date: datetime = None
) -> int:
    """
    Save macro articles to database.
    
    Args:
        supabase: Supabase client instance
        items: List of dicts in database format (from convert_to_db_format)
        collector: Collector name (for logging)
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
    
    inserted = 0
    for item in items:
        try:
            # Convert string ID to bigint for database
            string_id = item["id"]
            db_id = _string_id_to_bigint(string_id)
            
            # Prepare data for Supabase
            article_data = {
                "id": db_id,
                "title": item["title"],
                "summary": item.get("summary"),
                "url": item.get("url"),
                "source": item.get("source", "Unknown"),
                "published_at": item["published_at"].isoformat() if isinstance(item["published_at"], datetime) else item["published_at"],
                "created_at": item.get("created_at").isoformat() if isinstance(item.get("created_at"), datetime) else item.get("created_at"),
                "collector": item.get("collector", collector),
            }
            
            # Temporarily disabled optional fields:
            # if "source_domain" in item and item["source_domain"]:
            #     article_data["source_domain"] = item["source_domain"]
            # if "category_within_source" in item and item["category_within_source"]:
            #     article_data["category_within_source"] = item["category_within_source"]
            # if "authors" in item and item["authors"]:
            #     article_data["authors"] = item["authors"]
            # if "banner_image" in item and item["banner_image"]:
            #     article_data["banner_image"] = item["banner_image"]
            if "related_tickers" in item and item["related_tickers"]:
                article_data["related_tickers"] = item["related_tickers"]
            if "topics" in item and item["topics"]:
                article_data["topics"] = item["topics"]
            if "primary_topic" in item and item["primary_topic"]:
                article_data["primary_topic"] = item["primary_topic"]
            if "overall_sentiment_score" in item and item["overall_sentiment_score"] is not None:
                article_data["overall_sentiment_score"] = item["overall_sentiment_score"]
            if "overall_sentiment_label" in item and item["overall_sentiment_label"]:
                article_data["overall_sentiment_label"] = item["overall_sentiment_label"]
            
            # Include embedding if present (pgvector accepts list format)
            if "embedding" in item and item["embedding"] is not None:
                embedding = item["embedding"]
                if hasattr(embedding, 'tolist'):
                    article_data["embedding"] = embedding.tolist()
                elif isinstance(embedding, list):
                    article_data["embedding"] = embedding
            
            # Try to insert - Supabase will handle conflicts based on unique constraints
            # If URL exists, conflict is on url
            # Otherwise, conflict is on (title, published_at)
            result = supabase.table("macro_articles").insert(article_data).execute()
            
            if result.data:
                inserted += 1
        except Exception as e:
            # Supabase returns error for conflicts, which is expected for duplicates
            error_msg = str(e).lower()
            if "duplicate" in error_msg or "unique" in error_msg or "conflict" in error_msg:
                # This is a duplicate, skip it
                continue
            else:
                logger.error(f"Error inserting macro article: {e}")
                continue
    
    logger.info(f"Inserted {inserted} new macro articles from {collector}{date_range_str} (skipped {len(items) - inserted} duplicates)")
    return inserted
