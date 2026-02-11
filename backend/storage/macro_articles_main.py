"""
Main function for fetching and storing macro articles.
Uses Alpha Vantage NEWS_SENTIMENT API with topics parameter.
Fetches macro economic news, creates embeddings (OpenAI text-embedding-3-small),
and stores in macro_articles table.
"""
import asyncio
import argparse
import logging
import httpx
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set, Optional
from hashlib import md5
from difflib import SequenceMatcher

from backend.config import ALPHA_VANTAGE_API_KEY, ALPHA_VANTAGE_BASE_URL
from backend.storage.supabase_client import get_supabase_client
from backend.storage.macro_articles_save import convert_to_db_format, save_articles
from backend.storage.embedding_utils import get_embeddings as get_text_embeddings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Macro news topics to fetch (only economy-related topics)
MACRO_TOPICS = [
    "economy_fiscal",
    "economy_monetary",
    "economy_macro"
]


def _generate_article_id(url: str, time_published: str) -> str:
    """
    Generate a unique string ID for an article.
    
    Args:
        url: Article URL
        time_published: Publication time string
        
    Returns:
        String ID (e.g., "av_macro_a6af5309e89a")
    """
    # Use URL + time_published to generate unique ID
    id_string = f"{url}{time_published}"
    hash_bytes = md5(id_string.encode('utf-8')).digest()
    hash_hex = hash_bytes.hex()[:12]
    return f"av_macro_{hash_hex}"


def _extract_related_tickers(ticker_sentiment: List[Dict]) -> List[str]:
    """
    Extract ticker symbols from ticker_sentiment array.
    
    Args:
        ticker_sentiment: List of dicts with 'ticker' field from Alpha Vantage API
        
    Returns:
        List of uppercase ticker symbols
    """
    if not ticker_sentiment:
        return []
    
    tickers = []
    for item in ticker_sentiment:
        ticker = item.get("ticker", "").strip().upper()
        if ticker:
            tickers.append(ticker)
    
    return tickers


def _get_primary_topic(article: Dict[str, Any]) -> Optional[str]:
    """
    Get the topic with highest relevance_score from an article.
    
    Args:
        article: Article dict with 'topics' field
        
    Returns:
        Topic name with highest relevance_score, or None if no topics found
    """
    topics = article.get("topics", [])
    
    # If no topics, return None
    if not topics or not isinstance(topics, list):
        return None
    
    # Find the topic with highest relevance_score
    max_relevance = -1.0
    max_relevance_topic = None
    
    for topic_item in topics:
        if not isinstance(topic_item, dict):
            continue
        
        topic_name = topic_item.get("topic", "")
        relevance_score_str = topic_item.get("relevance_score", "0")
        
        try:
            relevance_score = float(relevance_score_str)
            if relevance_score > max_relevance:
                max_relevance = relevance_score
                max_relevance_topic = topic_name
        except (ValueError, TypeError):
            continue
    
    return max_relevance_topic


def _normalize_text(text: str) -> str:
    """
    Normalize text for similarity comparison.
    Removes extra whitespace, converts to lowercase, and removes common punctuation.
    
    Args:
        text: Input text
        
    Returns:
        Normalized text string
    """
    if not text:
        return ""
    # Convert to lowercase and remove extra whitespace
    normalized = " ".join(text.lower().split())
    # Remove common punctuation that doesn't affect meaning
    normalized = normalized.replace(".", "").replace(",", "").replace("'", "").replace('"', "")
    normalized = normalized.replace("!", "").replace("?", "").replace(":", "").replace(";", "")
    return normalized


def _calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using SequenceMatcher.
    
    Args:
        text1: First text
        text2: Second text
        
    Returns:
        Similarity score between 0.0 and 1.0
    """
    normalized1 = _normalize_text(text1)
    normalized2 = _normalize_text(text2)
    
    if not normalized1 or not normalized2:
        return 0.0
    
    return SequenceMatcher(None, normalized1, normalized2).ratio()


def _are_articles_similar(article1: Dict[str, Any], article2: Dict[str, Any], similarity_threshold: float = 0.85) -> bool:
    """
    Check if two articles are similar based on title and summary.
    
    Args:
        article1: First article dict
        article2: Second article dict
        similarity_threshold: Minimum similarity score to consider articles similar (default: 0.85)
        
    Returns:
        True if articles are similar, False otherwise
    """
    title1 = article1.get("title", "")
    title2 = article2.get("title", "")
    summary1 = article1.get("summary", "") or ""
    summary2 = article2.get("summary", "") or ""
    
    # Calculate title similarity
    title_similarity = _calculate_text_similarity(title1, title2)
    
    # Calculate summary similarity (if both have summaries)
    summary_similarity = 0.0
    if summary1 and summary2:
        summary_similarity = _calculate_text_similarity(summary1, summary2)
    
    # Combine title and summary similarity (weighted: title 70%, summary 30%)
    # If one article doesn't have summary, use only title similarity
    if summary1 and summary2:
        combined_similarity = title_similarity * 0.7 + summary_similarity * 0.3
    else:
        combined_similarity = title_similarity
    
    return combined_similarity >= similarity_threshold


def _deduplicate_similar_articles(articles: List[Dict[str, Any]], similarity_threshold: float = 0.85) -> List[Dict[str, Any]]:
    """
    Remove duplicate articles based on title and summary similarity.
    When duplicates are found, keeps the article with highest relevance_score.
    
    Args:
        articles: List of article dicts
        similarity_threshold: Minimum similarity score to consider articles duplicates (default: 0.85)
        
    Returns:
        List of deduplicated articles
    """
    if not articles:
        return []
    
    # Sort articles by relevance_score (descending) so we keep the best ones
    # First, calculate max relevance_score for each article
    articles_with_scores = []
    for article in articles:
        max_score = _get_max_relevance_score(article) or 0.0
        articles_with_scores.append((max_score, article))
    
    # Sort by relevance_score descending
    articles_with_scores.sort(key=lambda x: x[0], reverse=True)
    
    # Deduplicate: keep first occurrence (highest relevance_score)
    kept_articles = []
    for _, article in articles_with_scores:
        is_duplicate = False
        for kept_article in kept_articles:
            if _are_articles_similar(article, kept_article, similarity_threshold):
                is_duplicate = True
                logger.debug(
                    f"Found similar article: '{article.get('title', '')[:50]}' "
                    f"similar to '{kept_article.get('title', '')[:50]}' "
                    f"(keeping the one with higher relevance_score)"
                )
                break
        
        if not is_duplicate:
            kept_articles.append(article)
    
    return kept_articles


def _get_max_relevance_score(article: Dict[str, Any]) -> Optional[float]:
    """
    Get the highest relevance_score from an article's topics.
    
    Args:
        article: Article dict with 'topics' field
        
    Returns:
        Highest relevance_score as float, or None if no topics found
    """
    topics = article.get("topics", [])
    
    # If no topics, return None
    if not topics or not isinstance(topics, list):
        return None
    
    # Find the topic with highest relevance_score
    max_relevance = -1.0
    
    for topic_item in topics:
        if not isinstance(topic_item, dict):
            continue
        
        relevance_score_str = topic_item.get("relevance_score", "0")
        
        try:
            relevance_score = float(relevance_score_str)
            if relevance_score > max_relevance:
                max_relevance = relevance_score
        except (ValueError, TypeError):
            continue
    
    return max_relevance if max_relevance >= 0 else None


def _should_keep_article(article: Dict[str, Any]) -> bool:
    """
    Check if an article should be kept based on topic relevance.
    Only keep articles where:
    1. One of the macro topics (economy_fiscal, economy_monetary, economy_macro) has the highest relevance_score
    2. The highest relevance_score is greater than 0.9
    
    Args:
        article: Article dict with 'topics' field
        
    Returns:
        True if article should be kept, False otherwise
    """
    primary_topic = _get_primary_topic(article)
    max_relevance_score = _get_max_relevance_score(article)
    
    # Check if the highest relevance topic is one of our macro topics
    if primary_topic and primary_topic in MACRO_TOPICS:
        # Also check that the relevance_score is greater than 0.9
        if max_relevance_score is not None and max_relevance_score > 0.9:
            return True
    
    return False


async def fetch_macro_news_by_topic(
    client: httpx.AsyncClient,
    topic: str,
    time_from: datetime,
    time_to: datetime,
    api_key: str,
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """
    Fetch macro news from Alpha Vantage NEWS_SENTIMENT API for a specific topic.
    
    Args:
        client: HTTP client
        topic: Topic name (e.g., "financial_markets")
        time_from: Start time
        time_to: End time
        api_key: Alpha Vantage API key
        limit: Maximum number of articles to fetch
        
    Returns:
        List of article dicts
    """
    # Format time strings for Alpha Vantage API (YYYYMMDDTHHMM)
    time_from_str = time_from.strftime("%Y%m%dT%H%M")
    time_to_str = time_to.strftime("%Y%m%dT%H%M")
    
    params = {
        "function": "NEWS_SENTIMENT",
        "topics": topic,
        "time_from": time_from_str,
        "time_to": time_to_str,
        "limit": limit,
        "apikey": api_key
    }
    
    try:
        logger.info(f"Fetching macro news for topic '{topic}' ({time_from_str} to {time_to_str})...")
        response = await client.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        
        # Check for API errors
        if "Error Message" in data:
            logger.error(f"Alpha Vantage API error for topic {topic}: {data['Error Message']}")
            return []
        if "Note" in data:
            logger.warning(f"Alpha Vantage API note for topic {topic}: {data['Note']}")
            return []
        
        feed = data.get("feed", [])
        logger.info(f"Fetched {len(feed)} articles for topic '{topic}'")
        
        articles = []
        for item in feed:
            try:
                # Parse publication time
                time_str = item.get("time_published", "")
                try:
                    published_at = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                    published_at = published_at.replace(tzinfo=timezone.utc)
                except ValueError:
                    logger.warning(f"Invalid time format: {time_str}, skipping article")
                    continue
                
                # Filter by date range (API may return items outside range)
                if not (time_from <= published_at <= time_to):
                    continue
                
                # Extract related tickers
                ticker_sentiment = item.get("ticker_sentiment", [])
                related_tickers = _extract_related_tickers(ticker_sentiment)
                
                # Generate unique ID
                url = item.get("url", "")
                article_id = _generate_article_id(url, time_str)
                
                # Prepare article data with all available fields from API
                article_data = {
                    "id": article_id,
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "url": url,
                    "source": item.get("source", "Alpha Vantage"),
                    "source_domain": item.get("source_domain"),
                    "category_within_source": item.get("category_within_source"),
                    "authors": item.get("authors", []),
                    "banner_image": item.get("banner_image"),
                    "published_at": published_at,
                    "related_tickers": related_tickers,
                    "ticker_sentiment": item.get("ticker_sentiment", []),  # Pass full ticker_sentiment for extraction
                    "topics": item.get("topics", []),
                    "overall_sentiment_score": item.get("overall_sentiment_score"),
                    "overall_sentiment_label": item.get("overall_sentiment_label"),
                }
                
                articles.append(article_data)
            except Exception as e:
                logger.error(f"Error parsing article from topic {topic}: {e}")
                continue
        
        return articles
        
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching macro news for topic {topic}")
        return []
    except Exception as e:
        logger.error(f"Error fetching macro news for topic {topic}: {e}")
        return []


async def collect_macro_news(
    start_date: datetime,
    end_date: datetime,
    api_key: str = None,
    limit_per_topic: int = 1000,
    delay_between_calls: float = 2.0
) -> Dict[str, Any]:
    """
    Collect macro news from all topics.
    
    Args:
        start_date: Start date for collection
        end_date: End date for collection
        api_key: Alpha Vantage API key (uses config if None)
        limit_per_topic: Maximum articles per topic
        delay_between_calls: Delay in seconds between API calls
        
    Returns:
        Dict with collection results:
        - articles_by_topic: Dict mapping topic to list of articles
        - total_articles: Total unique articles
        - inserted_count: Number of articles inserted into database
    """
    if api_key is None:
        api_key = ALPHA_VANTAGE_API_KEY
    
    if not api_key:
        logger.error("ALPHA_VANTAGE_API_KEY not configured")
        return {
            "articles_by_topic": {},
            "total_articles": 0,
            "inserted_count": 0
        }
    
    # Ensure timezone-aware
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    
    articles_by_topic = {}
    all_articles = []
    seen_urls: Set[str] = set()
    seen_titles: Set[tuple] = set()
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, topic in enumerate(MACRO_TOPICS):
            try:
                # Fetch articles for this topic
                articles = await fetch_macro_news_by_topic(
                    client=client,
                    topic=topic,
                    time_from=start_date,
                    time_to=end_date,
                    api_key=api_key,
                    limit=limit_per_topic
                )
                
                articles_by_topic[topic] = articles
                
                # Deduplicate across topics
                for article in articles:
                    url = article.get("url", "")
                    title = article.get("title", "")
                    published_at = article.get("published_at")
                    
                    # Check for duplicates
                    if url:
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                    else:
                        # Use title + published_at as key if no URL
                        title_key = (title, published_at.isoformat() if published_at else "")
                        if title_key in seen_titles:
                            continue
                        seen_titles.add(title_key)
                    
                    all_articles.append(article)
                
                # Rate limiting: delay between API calls (except for last one)
                if i < len(MACRO_TOPICS) - 1:
                    await asyncio.sleep(delay_between_calls)
                    
            except Exception as e:
                logger.error(f"Error collecting macro news for topic {topic}: {e}")
                articles_by_topic[topic] = []
                continue
    
    # Filter articles: only keep those where a macro topic has the highest relevance_score
    # Also record the primary_topic (highest relevance_score topic) for each article
    filtered_articles = []
    filtered_out_count = 0
    
    for article in all_articles:
        primary_topic = _get_primary_topic(article)
        if _should_keep_article(article):
            # Record primary_topic in article data for saving
            article["primary_topic"] = primary_topic
            if not primary_topic:
                logger.warning(f"Article '{article.get('title', 'N/A')[:50]}' has no primary_topic but passed filter")
            filtered_articles.append(article)
        else:
            filtered_out_count += 1
    
    logger.info(f"Filtered articles: {len(filtered_articles)} kept, {filtered_out_count} filtered out (based on topic relevance)")
    
    # Deduplicate similar articles based on title and summary similarity
    deduplicated_articles = _deduplicate_similar_articles(filtered_articles, similarity_threshold=0.85)
    deduplication_count = len(filtered_articles) - len(deduplicated_articles)
    if deduplication_count > 0:
        logger.info(f"Deduplicated {deduplication_count} similar articles (kept {len(deduplicated_articles)} unique articles)")
    
    # Create embeddings for all unique articles we're saving (one per item in deduplicated_articles)
    if deduplicated_articles:
        texts = [(a.get("summary") or a.get("title") or "").strip() or "" for a in deduplicated_articles]
        try:
            embeddings = await get_text_embeddings(texts)
            if embeddings is not None and len(embeddings) == len(deduplicated_articles):
                for i, article in enumerate(deduplicated_articles):
                    article["embedding"] = embeddings[i].tolist()
                logger.info(f"Added embeddings for {len(deduplicated_articles)} macro articles")
            else:
                logger.warning("Failed to get embeddings for macro articles, saving without embeddings")
        except Exception as e:
            logger.warning(f"Embedding creation failed for macro articles: {e}, saving without embeddings")
    
    # Save to database
    inserted_count = 0
    if deduplicated_articles:
        try:
            supabase = get_supabase_client()
            
            # Convert to database format
            db_items = []
            for article in deduplicated_articles:
                db_item = convert_to_db_format(article, collector="alpha_vantage")
                db_items.append(db_item)
            
            # Save to database
            inserted_count = save_articles(
                supabase=supabase,
                items=db_items,
                collector="alpha_vantage",  # This collector name, can be changed for other sources
                start_date=start_date,
                end_date=end_date
            )
        except Exception as e:
            logger.error(f"Error saving macro articles to database: {e}")
    
    return {
        "articles_by_topic": articles_by_topic,
        "total_articles": len(all_articles),
        "filtered_articles": len(filtered_articles),
        "filtered_out_count": filtered_out_count,
        "deduplicated_articles": len(deduplicated_articles),
        "deduplication_count": deduplication_count,
        "inserted_count": inserted_count
    }


async def main(start_date: datetime = None, end_date: datetime = None):
    """
    Main function to collect macro news.
    
    Args:
        start_date: Start date (defaults to yesterday)
        end_date: End date (defaults to yesterday)
    """
    # Default to yesterday if not provided
    if end_date is None:
        end_date = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999) - timedelta(days=1)
    
    if start_date is None:
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Ensure timezone-aware
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    logger.info("=" * 60)
    logger.info(f"Starting macro news collection for date range: {start_str} to {end_str}")
    logger.info("=" * 60)
    
    # Collect macro news
    results = await collect_macro_news(start_date, end_date)
    
    # Print summary
    logger.info("=" * 60)
    logger.info("Collection Summary:")
    logger.info(f"  Date range: {start_str} to {end_str}")
    logger.info("  Articles by topic:")
    for topic, articles in results["articles_by_topic"].items():
        logger.info(f"    {topic}: {len(articles)} articles")
    logger.info(f"  Total unique articles fetched: {results['total_articles']}")
    logger.info(f"  Articles after relevance filtering: {results.get('filtered_articles', results['total_articles'])}")
    logger.info(f"  Articles filtered out: {results.get('filtered_out_count', 0)}")
    logger.info(f"  Articles after similarity deduplication: {results.get('deduplicated_articles', results.get('filtered_articles', results['total_articles']))}")
    logger.info(f"  Similar articles deduplicated: {results.get('deduplication_count', 0)}")
    logger.info(f"  Articles inserted into database: {results['inserted_count']}")
    logger.info("=" * 60)
    
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collect macro news from Alpha Vantage NEWS_SENTIMENT API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backend.storage.macro_articles_main                           # Collect for yesterday
  python -m backend.storage.macro_articles_main --date 2026-01-11         # Collect for specific date
  python -m backend.storage.macro_articles_main --start-date 2026-01-11 --end-date 2026-01-11  # Specific range

Date format: YYYY-MM-DD (e.g., 2026-01-11)
        """
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to collect news for (YYYY-MM-DD format, defaults to yesterday)"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD format"
    )
    
    args = parser.parse_args()
    
    # Parse dates
    parsed_start_date = None
    parsed_end_date = None
    
    if args.date:
        try:
            date_obj = datetime.strptime(args.date, "%Y-%m-%d")
            parsed_start_date = date_obj.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
            parsed_end_date = date_obj.replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
        except ValueError:
            print(f"ERROR: Invalid date format '{args.date}'. Use YYYY-MM-DD format.")
            exit(1)
    
    if args.end_date:
        try:
            parsed_end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
            parsed_end_date = parsed_end_date.replace(tzinfo=timezone.utc, hour=23, minute=59, second=59)
        except ValueError:
            print(f"ERROR: Invalid end-date format '{args.end_date}'. Use YYYY-MM-DD format.")
            exit(1)
    
    if args.start_date:
        try:
            parsed_start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
            parsed_start_date = parsed_start_date.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0)
        except ValueError:
            print(f"ERROR: Invalid start-date format '{args.start_date}'. Use YYYY-MM-DD format.")
            exit(1)
    
    # Validate date range
    if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
        print(f"ERROR: start-date ({parsed_start_date.date()}) must be before or equal to end-date ({parsed_end_date.date()})")
        exit(1)
    
    asyncio.run(main(start_date=parsed_start_date, end_date=parsed_end_date))
