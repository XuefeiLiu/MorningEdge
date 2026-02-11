"""
Supabase client connection module.
Replaces psycopg2 with Supabase Python client for database operations.
"""
import os
import logging
from typing import Optional
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://aqwuiwclckiqvlhsodxh.supabase.co")
SUPABASE_KEY = os.getenv("DB_API_KEY") or os.getenv("SUPABASE_KEY")

# Global Supabase client instance
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Get or create Supabase client instance.
    
    Returns:
        Supabase Client instance
        
    Raises:
        ValueError: If configuration is incomplete
    """
    global _supabase_client
    
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "Supabase configuration incomplete. Please set:\n"
                "  - SUPABASE_URL (or defaults to project URL)\n"
                "  - DB_API_KEY or SUPABASE_KEY (for database operations)"
            )
        
        try:
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info(f"Connected to Supabase: {SUPABASE_URL}")
            return _supabase_client
        except Exception as e:
            logger.error(f"Failed to create Supabase client: {e}")
            raise
    
    return _supabase_client


def reset_client() -> None:
    """Reset the global client (useful for testing)."""
    global _supabase_client
    _supabase_client = None
