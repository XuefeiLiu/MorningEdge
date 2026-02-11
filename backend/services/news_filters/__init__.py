"""
News filter module for filtering NewsItem objects by relevance to tickers.

This module provides different filtering strategies:
- KeywordFilter: Keyword-based relevance checking
- LLMFilter: AI-based relevance using OpenAI (requires OPENAI_API_KEY)
- GeminiFilter: AI-based relevance using Google Gemini
"""

from .base import NewsFilter
from .keyword_filter import KeywordRelevanceFilter
from .llm_filter import LLMFilter
from .gemini_filter import GeminiFilter
from .filter_factory import FilterFactory

# Backward compatibility alias
OpenAIFilter = LLMFilter

__all__ = [
    "NewsFilter",
    "KeywordRelevanceFilter",
    "LLMFilter",
    "OpenAIFilter",  # Backward compatibility
    "GeminiFilter",
    "FilterFactory",
]
