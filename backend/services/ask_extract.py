"""
Ask: extract related tickers or macro from user question when tickers are not provided.
Uses LLM to classify question (macro vs stock) and extract ticker symbols from our stocks dataset.
"""
import json
import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Max tickers to include in the prompt (keep prompt small)
ASK_EXTRACT_TICKER_LIST_MAX = 200


async def extract_tickers_or_macro(
    question: str,
    ticker_name_pairs: List[Tuple[str, str]],
    llm_client,
    model: str,
) -> Tuple[List[str], bool]:
    """
    Use LLM to determine: (1) is the question macro-related? (2) which tickers from our list are relevant?
    ticker_name_pairs: list of (ticker, name) e.g. [("AAPL", "Apple Inc."), ...].
    Returns (tickers_list, is_macro). tickers_list is empty if is_macro or none matched.
    """
    if not ticker_name_pairs:
        return [], False

    # Limit list size for prompt
    pairs = ticker_name_pairs[:ASK_EXTRACT_TICKER_LIST_MAX]
    ticker_list_str = "\n".join(f"{t}: {n}" for t, n in pairs)

    system = """You are a classifier for a financial Q&A system. Given a user question and a list of available stock tickers (ticker: company name), output JSON only with no markdown:
{"tickers": ["TICKER1", "TICKER2"], "is_macro": false}
- is_macro: true if the question is mainly about macroeconomics: Fed, interest rates, inflation, GDP, fiscal/monetary policy, commodities, FX, credit markets, or broad market. Otherwise false.
- tickers: list of ticker symbols FROM THE PROVIDED LIST that are relevant to the question. Use exact symbols (e.g. AAPL not Apple). If is_macro is true, you may leave tickers empty. If the question mentions specific companies, include their tickers. Return empty list if none apply."""

    user = f"""Available tickers (use only these symbols):
{ticker_list_str}

User question: {question}

Output JSON only: {{"tickers": [...], "is_macro": true/false}}"""

    try:
        response = await llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=200,
        )
        text = (response.choices[0].message.content or "").strip()
        # Strip markdown code block if present
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        data = json.loads(text)
        tickers = data.get("tickers") or []
        is_macro = bool(data.get("is_macro"))
        if not isinstance(tickers, list):
            tickers = []
        # Normalize to uppercase and filter to only symbols we have
        valid = {t.upper() for t, _ in pairs}
        tickers = [t.upper() for t in tickers if (t or "").upper() in valid][:10]
        return tickers, is_macro
    except Exception as e:
        logger.warning("Ask extract LLM failed: %s", e)
        return [], False
