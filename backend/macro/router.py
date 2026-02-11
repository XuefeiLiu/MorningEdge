"""
Rule-based topic/relevance routing for macro raw items.
Assigns topic (FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy, Monetary Policy, Trump),
relevance_score (int 0-100), and optional region. No LLM call.
"""
import logging
import re
from typing import Dict, Any, List

from backend.config import MACRO_TOPICS

logger = logging.getLogger(__name__)

# Keyword rules per topic (lowercase); first match wins for primary topic; relevance from match strength.
TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "FX": [
        "dollar", "yen", "euro", "currency", "forex", "fx", "exchange rate", "usd", "jpy", "eur", "gbp",
        "devaluation", "appreciation", "central bank intervention", "carry trade", "dxy",
    ],
    "RATE": [
        "interest rate", "fed", "fomc", "basis points", "bps", "yield", "treasury", "bond",
        "rate cut", "rate hike", "policy rate", "real rate", "nominal rate", "dot plot",
    ],
    "CREDIT": [
        "credit", "cds", "spread", "default", "high yield", "investment grade", "ig", "hy",
        "liquidity", "funding", "libor", "sofr", "basis", "swap spread",
    ],
    "COMMODITY": [
        "oil", "crude", "gold", "copper", "commodity", "opec", "natural gas", "wti", "brent",
    ],
    "EQUITY": [
        "stock", "equity", "s&p", "nasdaq", "dow", "market", "earnings", "valuation", "pe",
    ],
    "Fiscal Policy": [
        "fiscal", "deficit", "debt ceiling", "spending", "tax", "stimulus", "infrastructure",
        "congress", "budget", "treasury issuance",
    ],
    "Monetary Policy": [
        "monetary", "quantitative easing", "qe", "qt", "balance sheet", "inflation target",
        "ecb", "boj", "boe", "central bank", "hawkish", "dovish",
    ],
    "Trump": [
        "trump", "tariff", "trade war", "china tariff", "immigration", "executive order",
    ],
}


def _score_match(text: str, keywords: List[str]) -> int:
    """Return 0-100 relevance from keyword matches (count and density).
    No match -> 25 so MACRO_RAW_MIN_RELEVANCE=50 can filter noisy/off-topic items."""
    if not text:
        return 25
    lower = text.lower()
    hits = sum(1 for k in keywords if k in lower)
    if hits == 0:
        return 25
    # Cap at 100; more hits -> higher score
    return min(100, 50 + hits * 10)


def route_one(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assign topic, relevance_score (int 0-100), and optional region to one raw item.
    Uses title + summary for keyword matching. First topic with a match wins; relevance from match strength.
    """
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    combined = f"{title} {summary}"
    best_topic = None
    best_score = 0
    for topic in MACRO_TOPICS:
        keywords = TOPIC_KEYWORDS.get(topic, [])
        score = _score_match(combined, keywords)
        if score > best_score:
            best_score = score
            best_topic = topic
    if best_topic is None:
        best_topic = "Monetary Policy"  # default
        best_score = 25  # low so min_relevance filter can drop noisy/off-topic
    out = dict(item)
    out["topic"] = best_topic
    out["relevance_score"] = min(100, max(0, best_score))
    out["topic_candidate"] = item.get("topic_candidate") or item.get("primary_topic")
    out["region"] = item.get("region")  # keep if present; optional
    return out


def route_raw_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Route a list of raw items; return items with topic, relevance_score, region set."""
    return [route_one(it) for it in items]
