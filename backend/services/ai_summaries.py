"""
AI-powered summary generation using OpenAI API.

Provides one-click summaries of high-impact information,
highlighting key data points and changes.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import json

from backend.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_MAX_TOKENS
from backend.models import (
    NewsItem, MacroEvent, SECFiling, StockImpactSummary,
    ImpactLevel, AISummaryResponse
)

logger = logging.getLogger(__name__)

# Try to import OpenAI
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not installed. AI summaries will use fallback.")


class AISummaryGenerator:
    """
    Generates AI-powered summaries using OpenAI API.
    
    Falls back to rule-based summaries when:
    - OpenAI API key is not configured
    - OpenAI package is not installed
    - API call fails
    """
    
    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.model = OPENAI_MODEL
        self.max_tokens = OPENAI_MAX_TOKENS
        
        if OPENAI_AVAILABLE and self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)
            self.is_available = True
        else:
            self.client = None
            self.is_available = False
            if not OPENAI_AVAILABLE:
                logger.info("OpenAI package not available, using fallback summaries")
            elif not self.api_key:
                logger.info("OPENAI_API_KEY not configured, using fallback summaries")
    
    async def summarize_briefing(
        self,
        news: List[NewsItem],
        macro: List[MacroEvent],
        filings: List[SECFiling],
        stock_summaries: List[StockImpactSummary],
        focus_symbols: Optional[List[str]] = None
    ) -> AISummaryResponse:
        """
        Generate a comprehensive summary of the briefing.
        
        Args:
            news: List of news items
            macro: List of macro events
            filings: List of SEC filings
            stock_summaries: List of per-stock summaries
            focus_symbols: Optional list of symbols to focus on
            
        Returns:
            AISummaryResponse with summary and key points
        """
        if self.is_available:
            try:
                return await self._generate_openai_summary(
                    news, macro, filings, stock_summaries, focus_symbols
                )
            except Exception as e:
                logger.error(f"OpenAI API error: {e}")
                logger.info("Falling back to rule-based summary")
        
        return self._generate_fallback_summary(
            news, macro, filings, stock_summaries, focus_symbols
        )
    
    async def summarize_items(
        self,
        items: List[Dict[str, Any]],
        context: str = "market news"
    ) -> AISummaryResponse:
        """
        Summarize a list of arbitrary items.
        
        Args:
            items: List of items to summarize
            context: Context description for the summary
            
        Returns:
            AISummaryResponse
        """
        if self.is_available:
            try:
                return await self._generate_items_summary(items, context)
            except Exception as e:
                logger.error(f"OpenAI API error: {e}")
        
        return self._generate_fallback_items_summary(items)
    
    async def _generate_openai_summary(
        self,
        news: List[NewsItem],
        macro: List[MacroEvent],
        filings: List[SECFiling],
        stock_summaries: List[StockImpactSummary],
        focus_symbols: Optional[List[str]] = None
    ) -> AISummaryResponse:
        """Generate summary using OpenAI API."""
        # Prepare context
        context = self._prepare_context(news, macro, filings, stock_summaries, focus_symbols)
        
        prompt = f"""You are a financial analyst preparing a pre-market briefing. 
Analyze the following market data and provide:
1. A concise executive summary (2-3 sentences)
2. Key points that traders should focus on (bullet points)

Focus on actionable insights and potential market-moving events.
{f"Pay special attention to: {', '.join(focus_symbols)}" if focus_symbols else ""}

Market Data:
{context}

Respond in JSON format:
{{"summary": "...", "key_points": ["point 1", "point 2", ...]}}"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are an expert financial analyst."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=self.max_tokens,
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
        # Parse response
        content = response.choices[0].message.content
        try:
            result = json.loads(content)
            summary = result.get("summary", "Unable to generate summary.")
            key_points = result.get("key_points", [])
        except json.JSONDecodeError:
            summary = content
            key_points = []
        
        return AISummaryResponse(
            summary=summary,
            key_points=key_points,
            generated_at=datetime.utcnow()
        )
    
    async def _generate_items_summary(
        self,
        items: List[Dict[str, Any]],
        context: str
    ) -> AISummaryResponse:
        """Generate summary for arbitrary items using OpenAI."""
        items_text = "\n".join([
            f"- {item.get('title', item.get('description', str(item)))}"
            for item in items[:20]  # Limit items
        ])
        
        prompt = f"""Summarize the following {context}:

{items_text}

Provide:
1. A brief summary (1-2 sentences)
2. Key takeaways (3-5 bullet points)

Respond in JSON format:
{{"summary": "...", "key_points": ["point 1", "point 2", ...]}}"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a concise market analyst."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=self.max_tokens,
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        try:
            result = json.loads(content)
            summary = result.get("summary", "")
            key_points = result.get("key_points", [])
        except json.JSONDecodeError:
            summary = content
            key_points = []
        
        return AISummaryResponse(
            summary=summary,
            key_points=key_points,
            generated_at=datetime.utcnow()
        )
    
    def _prepare_context(
        self,
        news: List[NewsItem],
        macro: List[MacroEvent],
        filings: List[SECFiling],
        stock_summaries: List[StockImpactSummary],
        focus_symbols: Optional[List[str]] = None
    ) -> str:
        """Prepare context string for OpenAI prompt."""
        parts = []
        
        # High-impact news
        high_news = [n for n in news if n.impact_level == ImpactLevel.HIGH][:5]
        if high_news:
            parts.append("HIGH-IMPACT NEWS:")
            for n in high_news:
                parts.append(f"  - {n.title} ({n.ticker})")
        
        # Macro events
        if macro:
            parts.append("\nMACRO EVENTS:")
            for m in macro[:5]:
                parts.append(f"  - {m.title}: {m.actual_value or 'TBD'}")
        
        # SEC filings
        high_filings = [f for f in filings if f.impact_level == ImpactLevel.HIGH][:3]
        if high_filings:
            parts.append("\nSEC FILINGS:")
            for f in high_filings:
                parts.append(f"  - {f.symbol}: {f.form_type} - {f.description}")
        
        # Stock summaries
        if stock_summaries:
            parts.append("\nSTOCK SIGNALS:")
            for s in stock_summaries[:10]:
                if focus_symbols and s.symbol not in focus_symbols:
                    continue
                tech = s.technical_summary
                price_str = f" ({tech.change_percent:+.1f}%)" if tech and tech.change_percent else ""
                parts.append(
                    f"  - {s.symbol}: {s.trading_direction.value.upper()}{price_str} "
                    f"(confidence: {s.confidence_score:.0%})"
                )
        
        return "\n".join(parts)
    
    def _generate_fallback_summary(
        self,
        news: List[NewsItem],
        macro: List[MacroEvent],
        filings: List[SECFiling],
        stock_summaries: List[StockImpactSummary],
        focus_symbols: Optional[List[str]] = None
    ) -> AISummaryResponse:
        """Generate rule-based summary when OpenAI is unavailable."""
        key_points = []
        summary_parts = []
        
        # Count high-impact items
        high_news = [n for n in news if n.impact_level == ImpactLevel.HIGH]
        high_macro = [m for m in macro if m.impact_level == ImpactLevel.HIGH]
        high_filings = [f for f in filings if f.impact_level == ImpactLevel.HIGH]
        
        # Build summary
        if high_news:
            summary_parts.append(f"{len(high_news)} high-impact news items")
            key_points.append(f"Key news: {high_news[0].title[:80]}")
        
        if high_macro:
            summary_parts.append(f"{len(high_macro)} significant macro events")
            key_points.append(f"Macro: {high_macro[0].title}")
        
        if high_filings:
            summary_parts.append(f"{len(high_filings)} important SEC filings")
            key_points.append(f"SEC Filing: {high_filings[0].symbol} - {high_filings[0].form_type}")
        
        # Stock direction summary
        buy_signals = [s for s in stock_summaries if s.trading_direction.value == "buy"]
        sell_signals = [s for s in stock_summaries if s.trading_direction.value == "sell"]
        
        if buy_signals:
            symbols = ", ".join(s.symbol for s in buy_signals[:3])
            key_points.append(f"Bullish signals: {symbols}")
        
        if sell_signals:
            symbols = ", ".join(s.symbol for s in sell_signals[:3])
            key_points.append(f"Bearish signals: {symbols}")
        
        # Generate summary text
        if summary_parts:
            summary = f"Pre-market briefing shows {', '.join(summary_parts)}. "
        else:
            summary = "Pre-market briefing shows normal market conditions. "
        
        if buy_signals or sell_signals:
            summary += f"Trading signals: {len(buy_signals)} bullish, {len(sell_signals)} bearish."
        else:
            summary += "Most stocks showing neutral signals."
        
        return AISummaryResponse(
            summary=summary,
            key_points=key_points[:5],
            generated_at=datetime.utcnow()
        )
    
    def _generate_fallback_items_summary(
        self,
        items: List[Dict[str, Any]]
    ) -> AISummaryResponse:
        """Generate simple fallback summary for items."""
        if not items:
            return AISummaryResponse(
                summary="No items to summarize.",
                key_points=[],
                generated_at=datetime.utcnow()
            )
        
        # Extract titles/descriptions
        titles = []
        for item in items[:5]:
            title = item.get("title") or item.get("description") or str(item)
            titles.append(title[:100])
        
        summary = f"Summary of {len(items)} items."
        key_points = [f"• {t}" for t in titles]
        
        return AISummaryResponse(
            summary=summary,
            key_points=key_points,
            generated_at=datetime.utcnow()
        )


# Global instance
ai_summary_generator = AISummaryGenerator()
