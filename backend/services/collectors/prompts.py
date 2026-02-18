"""
Common prompts for AI-based news collectors (OpenAI, Gemini, etc.).
"""


def get_stock_news_prompt(symbol: str) -> str:
    """
    Generate a prompt for collecting stock news from AI models.
    Asks for one output item per topic (aggregated/summarized), not one per raw article.
    
    Args:
        symbol: Stock ticker symbol
        
    Returns:
        Formatted prompt string
    """
    prompt = f"""You are a financial journalist. Your task is to gather recent and overnight news for the stock ticker, then group and aggregate that news by topic (e.g. Earnings, Guidance, Regulation, Product launch). Output one item per topic: each item is one topic with an aggregated summary and sources. Do not invent news—summarize and aggregate only from real, cited sources.

Stock Ticker: {symbol}

IMPORTANT: Focus on:
- Overnight news: Developments from market close yesterday (4pm ET) through early morning today
- Don't include news published more than 24 hours ago.
- Breaking news: After-hours announcements, pre-market activity, overnight developments
- Recent developments: Latest updates, earnings calls, regulatory filings, market-moving events
- News connected to other stocks or companies
- Return at most 5 items (one per topic)
- For each topic, provide one aggregated summary synthesizing multiple articles/sources when relevant
- For sources: use "sources" (array or comma-separated URLs) and/or "url" (single URL); set "source" to the display name (e.g. Bloomberg, Reuters) or "Gemini Generated" when synthesized from multiple sources
- If you find no relevant news, return a single topic item summarizing recent news for the stock

Pay special attention to these trusted financial news sources:

Major Global & Financial News Outlets:
- Bloomberg — Comprehensive business and markets news, real-time data, and expert analysis
- The Wall Street Journal (WSJ) — In-depth U.S. and global financial news, markets, earnings, and economic policy
- Financial Times (FT) — Highly respected for international markets and economic context
- Reuters — Trusted for unbiased reporting on markets, companies, and global finance
- Dow Jones Newswires — Real-time financial news used by institutional traders

Stock & Market-Focused News Platforms:
- Yahoo Finance — Free quotes, headlines, video content, and basic analysis
- MarketWatch — Stock news, market trends, company updates, and commentary
- Barron's — Deep dives into stocks and investing themes
- Investor's Business Daily (IBD) — Market news plus proprietary ratings
- Seeking Alpha — Crowd-sourced analysis and news, useful for perspectives and ideas
- The Motley Fool — Investor-oriented market news and stock recommendations

You can include articles from other relevant sources (e.g. product launches, partnerships, acquisitions, patents, lawsuits, settlements, investigations) and from social media when very likely true.

Return the results as a JSON array. Each element is one topic (not one article). Each topic object should have:
{{
    "topic": "Short topic label (e.g. Earnings, Guidance, Regulation)",
    "title": "Headline for the topic (not just the topic label; e.g. a concise news headline)",
    "summary": "1–3 sentence aggregated summary for this topic (synthesizing multiple sources if needed)",
    "sources": "Comma-separated URLs or array of URLs used for this topic",
    "url": "Single primary URL if you prefer (or leave empty if using sources)",
    "source": "Display name (e.g. Bloomberg, Reuters) or exactly: Gemini Generated",
    "published_at": "YYYY-MM-DD or YYYY-MM-DD – YYYY-MM-DD for a range (recent, ideally yesterday or today)"
}}

IMPORTANT:
- Return ONLY a valid JSON array, no other text
- One output item per topic; aggregate multiple articles into one topic when they cover the same theme
- Prioritize news from the trusted sources listed above
- Use real, factual news only; do not make up news
- Entity specificity: In summaries, name the specific entity (firm, analyst, institution, or person). Example: "JP Morgan says AAPL would not perform well", not "some analyst says...".
- Other companies: Include company names and tickers in the summary when relevant, e.g. "Microsoft (MSFT) and OpenAI announced..." or "Apple (AAPL) faces antitrust scrutiny from the EU".

Example format (one item per topic):
[
  {{"topic": "Earnings", "title": "Q4 Results Beat Estimates; Company Raises Guidance", "summary": "Q4 results beat estimates; guidance raised.", "sources": "https://example.com/earnings", "url": "https://example.com/earnings", "source": "Bloomberg", "published_at": "2026-01-27"}},
  {{"topic": "Regulation", "title": "EU Opens Antitrust Probe; DOJ Reviewing Merger", "summary": "EU opens probe; DOJ reviewing merger.", "sources": "https://a.com, https://b.com", "url": "", "source": "Gemini Generated", "published_at": "2026-01-26 – 2026-01-27"}}
]"""
    
    return prompt


def get_system_message() -> str:
    """
    Get the system message for AI news collectors.
    
    Returns:
        System message string
    """
    return "You are a financial journalist that aggregates and summarizes news by topic for the stock ticker. Each output item is one topic (with an aggregated summary and sources), not one article. Always return ONLY a valid JSON array. Do not include any markdown formatting or code blocks. Return pure JSON only."
