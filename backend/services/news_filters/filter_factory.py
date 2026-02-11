"""
Factory for creating news filter instances.
"""
import logging
from typing import Optional, Dict, Any

from .base import NewsFilter
from .keyword_filter import KeywordRelevanceFilter
from .llm_filter import LLMFilter
from .gemini_filter import GeminiFilter

logger = logging.getLogger(__name__)


class FilterFactory:
    """
    Factory class for creating news filter instances.
    """
    
    @staticmethod
    def create_filter(
        filter_type: str,
        **kwargs
    ) -> NewsFilter:
        """
        Create a news filter instance based on the filter type.
        
        Args:
            filter_type: Type of filter to create. Options:
                - "keyword": Keyword-based relevance filter
                - "openai" or "llm": OpenAI API-based LLM filter (requires OPENAI_API_KEY)
                - "gemini": Gemini-based AI filter
            **kwargs: Additional arguments to pass to the filter constructor
                - For "keyword": keywords, relevance_threshold
                - For "openai"/"llm": batch_size, use_fallback (OPENAI_API_KEY must be configured)
                - For "gemini": api_key, model, batch_size, use_fallback
        
        Returns:
            NewsFilter instance
            
        Raises:
            ValueError: If filter_type is not recognized
        """
        filter_type_lower = filter_type.lower()
        
        if filter_type_lower == "keyword":
            return KeywordRelevanceFilter(
                keywords=kwargs.get("keywords"),
                relevance_threshold=kwargs.get("relevance_threshold")
            )
        
        elif filter_type_lower == "openai" or filter_type_lower == "llm":
            return LLMFilter(
                batch_size=kwargs.get("batch_size"),
                use_fallback=kwargs.get("use_fallback", True)
            )
        
        elif filter_type_lower == "gemini":
            return GeminiFilter(
                api_key=kwargs.get("api_key"),
                model=kwargs.get("model"),
                batch_size=kwargs.get("batch_size"),
                use_fallback=kwargs.get("use_fallback", True)
            )
        
        else:
            raise ValueError(
                f"Unknown filter type: {filter_type}. "
                f"Supported types: 'keyword', 'openai', 'gemini'"
            )
    
    @staticmethod
    def get_available_filters() -> list[str]:
        """
        Get list of available filter types.
        
        Returns:
            List of available filter type names
        """
        return ["keyword", "openai", "gemini"]
