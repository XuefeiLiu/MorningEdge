"""
Filtering and deduplication services for collected data.
"""
import re
import logging
from datetime import datetime
from typing import List, Set, Optional, Dict, Any
from difflib import SequenceMatcher
from hashlib import md5

from backend.config import (
    DEFAULT_KEYWORDS,
    RELEVANCE_THRESHOLD,
    DUPLICATE_SIMILARITY_THRESHOLD,
    OPENAI_API_KEY,
    OPENAI_MODEL
)
from backend.models import NewsItem, Category

logger = logging.getLogger(__name__)

# Try to import OpenAI
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not installed. Financial news filtering will use keyword fallback.")


class DataFilter:
    """Filters and deduplicates collected data based on relevance and keywords."""
    
    def __init__(
        self,
        keywords: Optional[List[str]] = None,
        relevance_threshold: float = RELEVANCE_THRESHOLD,
        similarity_threshold: float = DUPLICATE_SIMILARITY_THRESHOLD
    ):
        self.keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
        self.relevance_threshold = relevance_threshold
        self.similarity_threshold = similarity_threshold
        self._seen_hashes: Set[str] = set()
        self._seen_titles: List[str] = []
    
    def reset(self) -> None:
        """Reset the deduplication state."""
        self._seen_hashes.clear()
        self._seen_titles.clear()
    
    def filter_news(
        self,
        news_items: List[NewsItem],
        target_symbols: List[str]
    ) -> List[NewsItem]:
        """
        Filter news items based on relevance to symbols and keywords.
        Also removes duplicates (language-aware).
        
        Args:
            news_items: List of news items to filter
            target_symbols: List of symbols to check relevance against
            
        Returns:
            Filtered and deduplicated list of news items
        """
        filtered = []
        target_symbols_lower = [s.lower() for s in target_symbols]
        
        # Group by language for language-aware deduplication
        by_language: Dict[Optional[str], List[NewsItem]] = {}
        for item in news_items:
            lang = getattr(item, 'language', None)
            if lang not in by_language:
                by_language[lang] = []
            by_language[lang].append(item)
        
        # Process each language group separately
        for lang, lang_items in by_language.items():
            for item in lang_items:
                # Check for duplicates (within same language)
                if self._is_duplicate(item, lang):
                    logger.debug(f"Duplicate filtered: {item.title[:50]} (lang={lang})")
                    continue
                
                # Calculate relevance score
                relevance = self._calculate_relevance(
                    item, target_symbols_lower
                )
                
                # Filter by threshold
                if relevance < self.relevance_threshold:
                    logger.debug(f"Low relevance filtered: {item.title[:50]} ({relevance:.2f} < {self.relevance_threshold})")
                    # Log more details for debugging
                    logger.debug(f"  - Title: {item.title[:100]}")
                    logger.debug(f"  - Ticker in item: {item.ticker}")
                    logger.debug(f"  - Target symbols: {target_symbols}")
                    continue
                
                # Extract matched keywords
                item.keywords_matched = self._extract_matched_keywords(item)
                
                filtered.append(item)
        
        return filtered
    
    def _is_duplicate(self, item: NewsItem, language: Optional[str] = None) -> bool:
        """
        Check if an item is a duplicate of previously seen items.
        Language-aware: Don't deduplicate across languages.
        
        Args:
            item: News item to check
            language: Language code for language-aware deduplication
            
        Returns:
            True if duplicate, False otherwise
        """
        # Check exact hash duplicate (language-aware)
        content_hash = md5(
            f"{item.title}{item.url}{language or ''}".encode()
        ).hexdigest()
        
        if content_hash in self._seen_hashes:
            return True
        
        # Check similar title (fuzzy matching) - only within same language
        title_lower = item.title.lower()
        # Filter seen titles by language if language-aware deduplication is enabled
        # For now, we check all titles but this could be optimized
        for seen_title in self._seen_titles:
            similarity = SequenceMatcher(
                None, title_lower, seen_title
            ).ratio()
            if similarity >= self.similarity_threshold:
                return True
        
        # Not a duplicate, add to seen
        self._seen_hashes.add(content_hash)
        self._seen_titles.append(title_lower)
        
        return False
    
    def _calculate_relevance(
        self,
        item: NewsItem,
        target_symbols: List[str]
    ) -> float:
        """
        Calculate relevance score for a news item.
        
        Scoring factors:
        - Symbol mention in title/summary: +0.4
        - Keyword matches: +0.1 per keyword (max 0.4)
        - Source reliability: +0.1 for known sources
        - Recency: +0.1 for items < 6 hours old
        """
        score = 0.0
        
        text = f"{item.title} {item.summary or ''}".lower()
        
        # Symbol relevance
        for symbol in target_symbols:
            if symbol in text or symbol.upper() == item.ticker.upper():
                score += 0.4
                break
        
        # Keyword matches
        keyword_matches = 0
        for keyword in self.keywords:
            if keyword in text:
                keyword_matches += 1
        score += min(keyword_matches * 0.1, 0.4)
        
        # Source reliability bonus
        reliable_sources = [
            "reuters", "bloomberg", "wsj", "cnbc", "sec",
            "nasdaq", "alpha vantage", "fred"
        ]
        if any(src in item.source.lower() for src in reliable_sources):
            score += 0.1
        
        # Recency bonus (items less than 6 hours old)
        age_hours = (datetime.utcnow() - item.published_at.replace(tzinfo=None)).total_seconds() / 3600
        if age_hours < 6:
            score += 0.1
        
        return min(score, 1.0)
    
    def _extract_matched_keywords(self, item: NewsItem) -> List[str]:
        """Extract keywords that matched in the item."""
        text = f"{item.title} {item.summary or ''}".lower()
        matched = []
        
        for keyword in self.keywords:
            if keyword in text:
                matched.append(keyword)
        
        return matched[:10]  # Limit to 10 keywords
    
    def filter_by_symbols(
        self,
        items: List[Any],
        target_symbols: List[str],
        symbol_attr: str = "symbol"
    ) -> List[Any]:
        """
        Filter items to only include those matching target symbols.
        
        Args:
            items: List of items with a symbol attribute
            target_symbols: List of symbols to keep
            symbol_attr: Name of the attribute containing the symbol
            
        Returns:
            Filtered list of items
        """
        target_set = set(s.upper() for s in target_symbols)
        filtered = []
        
        for item in items:
            item_symbol = getattr(item, symbol_attr, None)
            if item_symbol and item_symbol.upper() in target_set:
                filtered.append(item)
        
        return filtered
    
    def deduplicate_by_id(self, items: List[Any]) -> List[Any]:
        """Remove items with duplicate IDs."""
        seen_ids: Set[str] = set()
        unique = []
        
        for item in items:
            item_id = getattr(item, "id", None)
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                unique.append(item)
        
        return unique
    
    def cross_source_deduplicate(
        self,
        news_items: List[NewsItem],
        source_priority: Optional[Dict[str, int]] = None
    ) -> List[NewsItem]:
        """
        Deduplicate news items across multiple sources.
        When duplicates are found, keeps the item from the highest priority source.
        
        Args:
            news_items: List of news items from multiple sources
            source_priority: Dict mapping source names to priority (lower = higher priority)
            
        Returns:
            Deduplicated list of news items
        """
        if not source_priority:
            source_priority = {}
        
        # Group by language for language-aware deduplication
        by_language: Dict[Optional[str], List[NewsItem]] = {}
        for item in news_items:
            lang = getattr(item, 'language', None)
            if lang not in by_language:
                by_language[lang] = []
            by_language[lang].append(item)
        
        unique_items = []
        
        # Deduplicate within each language group
        for lang, lang_items in by_language.items():
            # Group by similarity (title + URL hash)
            item_groups: Dict[str, List[NewsItem]] = {}
            
            for item in lang_items:
                # Create hash key
                title_lower = item.title.lower()
                url = item.url or ""
                hash_key = md5(f"{title_lower}{url}".encode()).hexdigest()
                
                # Also check for similar titles
                group_key = None
                for existing_key, group in item_groups.items():
                    # Check if similar to any item in existing group
                    for existing_item in group:
                        existing_title = existing_item.title.lower()
                        similarity = SequenceMatcher(
                            None, title_lower, existing_title
                        ).ratio()
                        if similarity >= self.similarity_threshold:
                            group_key = existing_key
                            break
                    if group_key:
                        break
                
                if not group_key:
                    group_key = hash_key
                
                if group_key not in item_groups:
                    item_groups[group_key] = []
                item_groups[group_key].append(item)
            
            # For each group, keep the item from highest priority source
            for group in item_groups.values():
                if len(group) == 1:
                    unique_items.append(group[0])
                else:
                    # Sort by source priority
                    def get_priority(item: NewsItem) -> int:
                        source = item.source.split("-")[0]  # Handle "NewsNow-platform" format
                        return source_priority.get(source, 999)
                    
                    sorted_group = sorted(group, key=get_priority)
                    unique_items.append(sorted_group[0])
                    logger.debug(f"Deduplicated {len(group)} items, kept from {sorted_group[0].source}")
        
        return unique_items


class FinancialNewsFilter:
    """
    Filters news items to only include financial/economic/macro news.
    Uses AI (OpenAI) for classification, with keyword-based fallback.
    """
    
    # Financial/Economic keywords for fallback (English and Chinese)
    FINANCIAL_KEYWORDS = [
        # English keywords
        "stock", "market", "economy", "economic", "finance", "financial", "bank", "banking",
        "investment", "investor", "trading", "trade", "currency", "dollar", "yuan", "euro",
        "inflation", "deflation", "gdp", "unemployment", "employment", "jobs", "wage",
        "interest rate", "fed", "federal reserve", "central bank", "monetary policy",
        "fiscal policy", "budget", "debt", "deficit", "surplus", "recession", "growth",
        "earnings", "revenue", "profit", "loss", "quarterly", "annual", "forecast",
        "acquisition", "merger", "ipo", "dividend", "buyback", "layoff",
        "oil", "crude", "gold", "silver", "commodity", "commodities", "crypto", "bitcoin",
        "bond", "treasury", "yield", "spread", "index", "dow", "s&p", "nasdaq",
        # Chinese keywords (simplified)
        "股票", "股市", "市场", "经济", "金融", "银行", "投资", "交易", "货币", "汇率",
        "通胀", "通缩", "GDP", "失业", "就业", "工资", "利率", "美联储", "央行", "货币政策",
        "财政政策", "预算", "债务", "赤字", "盈余", "衰退", "增长", "收益", "收入", "利润",
        "亏损", "季度", "年度", "预测", "收购", "合并", "IPO", "分红", "回购", "裁员",
        "石油", "原油", "黄金", "白银", "大宗商品", "加密货币", "比特币", "债券", "国债",
        "收益率", "利差", "指数", "道指", "标普", "纳斯达克", "A股", "港股", "美股",
        "人民币", "美元", "欧元", "日元", "英镑", "汇率", "贬值", "升值", "加息", "降息",
        "财报", "业绩", "业绩预告", "业绩快报", "年报", "季报", "中报", "一季报", "三季报",
        "涨停", "跌停", "涨停板", "跌停板", "牛市", "熊市", "震荡", "调整", "反弹", "回调",
        "板块", "行业", "概念", "题材", "热点", "龙头", "蓝筹", "成长股", "价值股",
        "基金", "私募", "公募", "券商", "保险", "信托", "期货", "期权", "ETF",
        "监管", "政策", "改革", "开放", "创新", "科技", "新能源", "人工智能", "AI",
        "消费", "零售", "房地产", "基建", "制造业", "服务业", "出口", "进口", "贸易",
    ]
    
    def __init__(
        self,
        use_ai: bool = True,
        batch_size: int = 20,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize financial news filter.
        
        Args:
            use_ai: Whether to use AI for classification (default: True)
            batch_size: Number of titles to classify in one API call (default: 20)
            api_key: OpenAI API key (default: from config)
            model: OpenAI model name (default: from config)
        """
        self.use_ai = use_ai and OPENAI_AVAILABLE and (api_key or OPENAI_API_KEY)
        self.batch_size = batch_size
        self.api_key = api_key or OPENAI_API_KEY
        self.model = model or OPENAI_MODEL
        
        if self.use_ai:
            self.client = AsyncOpenAI(api_key=self.api_key)
            logger.info("FinancialNewsFilter: Using AI-based classification")
        else:
            self.client = None
            if not OPENAI_AVAILABLE:
                logger.info("FinancialNewsFilter: OpenAI package not available, using keyword fallback")
            elif not self.api_key:
                logger.info("FinancialNewsFilter: OpenAI API key not configured, using keyword fallback")
            else:
                logger.info("FinancialNewsFilter: AI disabled, using keyword fallback")
    
    async def filter_financial_news(
        self,
        titles: List[str]
    ) -> List[bool]:
        """
        Filter titles to identify which are financial/economic/macro news.
        
        Args:
            titles: List of news titles to classify
            
        Returns:
            List of booleans indicating if each title is financial news
        """
        if not titles:
            return []
        
        if self.use_ai:
            try:
                return await self._classify_with_ai(titles)
            except Exception as e:
                logger.warning(f"AI classification failed, falling back to keywords: {e}")
                return self._classify_with_keywords(titles)
        else:
            return self._classify_with_keywords(titles)
    
    async def _classify_with_ai(self, titles: List[str]) -> List[bool]:
        """
        Classify titles using OpenAI API.
        
        Args:
            titles: List of news titles to classify
            
        Returns:
            List of booleans indicating if each title is financial news
        """
        results = []
        
        # Process in batches
        for i in range(0, len(titles), self.batch_size):
            batch = titles[i:i + self.batch_size]
            
            # Create prompt
            titles_text = "\n".join([f"{j+1}. {title}" for j, title in enumerate(batch)])
            prompt = f"""You are a financial news classifier. Determine if each news title is related to finance, economics, or macro events.

Categories include:
- Stock markets, trading, investments
- Economic indicators (GDP, inflation, unemployment, etc.)
- Central bank policies, interest rates
- Corporate earnings, financial results
- Mergers, acquisitions, IPOs
- Commodities (oil, gold, etc.)
- Currency exchange rates
- Financial regulations and policies
- Market trends and analysis

Exclude:
- Entertainment, sports, celebrity news
- General politics (unless economic policy)
- Technology news (unless financial/economic impact)
- Social issues (unless economic impact)

Return a JSON array of booleans, one for each title (true if financial/economic, false otherwise).

Titles:
{titles_text}

Response format: [true, false, true, ...]"""

            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a financial news classifier. Please filter out all non-financial news and keep news only related to Macro economy. Return only valid JSON arrays."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,
                    max_tokens=200
                )
                
                content = response.choices[0].message.content.strip()
                
                # Parse JSON response
                import json
                # Remove markdown code blocks if present
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                content = content.strip()
                
                batch_results = json.loads(content)
                
                # Validate length
                if len(batch_results) != len(batch):
                    logger.warning(f"AI returned {len(batch_results)} results for {len(batch)} titles, using keyword fallback for this batch")
                    batch_results = self._classify_with_keywords(batch)
                
                results.extend(batch_results)
                
            except Exception as e:
                logger.error(f"Error in AI classification for batch: {e}")
                # Fallback to keywords for this batch
                batch_results = self._classify_with_keywords(batch)
                results.extend(batch_results)
        
        return results
    
    def _classify_with_keywords(self, titles: List[str]) -> List[bool]:
        """
        Classify titles using keyword matching (fallback method).
        
        Args:
            titles: List of news titles to classify
            
        Returns:
            List of booleans indicating if each title is financial news
        """
        results = []
        
        for title in titles:
            if not title:
                results.append(False)
                continue
            
            title_lower = title.lower()
            
            # Check if any financial keyword appears in the title
            is_financial = any(
                keyword.lower() in title_lower
                for keyword in self.FINANCIAL_KEYWORDS
            )
            
            results.append(is_financial)
        
        return results
    
    def is_financial_news(self, title: str) -> bool:
        """
        Synchronous method to check if a single title is financial news.
        Uses keyword matching (for synchronous contexts).
        
        Args:
            title: News title to check
            
        Returns:
            True if financial news, False otherwise
        """
        if not title:
            return False
        
        title_lower = title.lower()
        return any(
            keyword.lower() in title_lower
            for keyword in self.FINANCIAL_KEYWORDS
        )


class TimeWindowFilter:
    """Filter data by time window."""
    
    def __init__(self, start_time: datetime, end_time: datetime):
        self.start_time = start_time.replace(tzinfo=None)
        self.end_time = end_time.replace(tzinfo=None)
    
    def filter_by_time(
        self,
        items: List[Any],
        time_attr: str = "published_at"
    ) -> List[Any]:
        """
        Filter items by time window.
        
        Args:
            items: List of items with a datetime attribute
            time_attr: Name of the datetime attribute
            
        Returns:
            Items within the time window
        """
        filtered = []
        
        for item in items:
            item_time = getattr(item, time_attr, None)
            if item_time is None:
                continue
            
            # Remove timezone info for comparison
            if hasattr(item_time, 'replace'):
                item_time = item_time.replace(tzinfo=None)
            
            if self.start_time <= item_time <= self.end_time:
                filtered.append(item)
        
        return filtered
