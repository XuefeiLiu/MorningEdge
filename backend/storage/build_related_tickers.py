"""
Build RELATED_TICKERS from the stocks table using OpenAI (with web search) and AI.

For each ticker in the stocks table, asks the model to identify related US stock tickers
(competitors, key suppliers, major customers). Outputs a JSON file that config can load
as the default RELATED_TICKERS dict.

Usage (from project root):
  python -m backend.storage.build_related_tickers
  python -m backend.storage.build_related_tickers --limit 5   # first 5 tickers only
  python -m backend.storage.build_related_tickers --output data/related_tickers.json
"""
import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_openai_related_tickers(
    ticker: str,
    company_name: str,
    valid_tickers: set,
    client,
    model: str = "gpt-4o",
    use_web_search: bool = True,
) -> list[str]:
    """
    Call OpenAI (with optional web search) to get related tickers for a stock.
    Returns only tickers that are in valid_tickers.
    """
    prompt = f"""For the US stock ticker {ticker} ({company_name or ticker}), identify related US stock tickers in these categories:
- Main competitors (direct competitors in the same industry)
- Key suppliers (major suppliers if publicly traded)
- Major customers (major customers if publicly traded)

Use web search if needed to find current, accurate relationships. Return ONLY a valid JSON array of ticker symbols (uppercase), e.g. ["MSFT", "GOOGL", "META"]. Include 5 to 15 tickers. Do not include the ticker itself. No other text or markdown."""

    try:
        if use_web_search and hasattr(client, "responses"):
            response = client.responses.create(
                model=model,
                tools=[{"type": "web_search"}],
                tool_choice={"type": "web_search"},
                input=prompt,
            )
            content = _extract_responses_api_content(response)
        else:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=500,
            )
            content = (response.choices[0].message.content or "").strip()

        if not content:
            return []

        # Strip markdown code blocks
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        content = content.strip()

        raw = json.loads(content)
        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, str) else []
        # Normalize to uppercase and filter to valid tickers only
        result = []
        for t in raw:
            if isinstance(t, str):
                u = t.strip().upper()
                if u and u in valid_tickers and u != ticker.upper():
                    result.append(u)
        return list(dict.fromkeys(result))  # dedupe preserve order
    except Exception as e:
        logger.warning(f"OpenAI call for {ticker} failed: {e}")
        return []


def _extract_responses_api_content(response) -> str:
    """Extract text content from OpenAI Responses API output."""
    content = None
    if hasattr(response, "output") and response.output:
        out = response.output
        if isinstance(out, list):
            for item in out:
                if getattr(item, "type", None) == "message" and hasattr(item, "content") and item.content:
                    if isinstance(item.content, list):
                        text_parts = []
                        for c in item.content:
                            if hasattr(c, "text") and c.text:
                                text_parts.append(c.text)
                        content = " ".join(text_parts) if text_parts else None
                    elif hasattr(item.content, "text") and item.content.text:
                        content = item.content.text
                    if content:
                        break
        if content is None and hasattr(out, "__getitem__") and len(out) > 0:
            first = out[0]
            if hasattr(first, "content") and first.content:
                if isinstance(first.content, list) and len(first.content) > 0 and hasattr(first.content[0], "text"):
                    content = first.content[0].text
                elif hasattr(first.content, "text"):
                    content = first.content.text
    if not isinstance(content, str):
        content = str(content) if content else ""
    return (content or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build RELATED_TICKERS from stocks table using OpenAI and web search"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N tickers (for testing)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path (default: data/related_tickers.json)",
    )
    parser.add_argument(
        "--no-web-search",
        action="store_true",
        help="Use chat completions only, no Responses API web search",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between API calls (default: 2)",
    )
    args = parser.parse_args()

    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package required: pip install openai")
        return

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set in environment")
        return

    try:
        from backend.storage.supabase_client import get_supabase_client
        from backend.storage.stocks_query import get_all_stocks
    except ImportError:
        logger.error("Run from project root with PYTHONPATH=. (e.g. python -m backend.storage.build_related_tickers)")
        return

    # Output path
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path(_project_root()) / "data" / "related_tickers.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Load stocks and valid tickers
    supabase = get_supabase_client()
    stocks = get_all_stocks(supabase)
    if not stocks:
        logger.error("No stocks found in database")
        return

    valid_tickers = {s["ticker"].upper() for s in stocks}
    tickers_to_process = [s for s in stocks]
    if args.limit:
        tickers_to_process = tickers_to_process[: args.limit]
        logger.info(f"Processing first {args.limit} tickers (of {len(stocks)})")
    else:
        logger.info(f"Processing {len(tickers_to_process)} tickers")

    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    client = OpenAI(api_key=api_key)
    use_web_search = not args.no_web_search

    related: dict[str, list[str]] = {}
    for i, stock in enumerate(tickers_to_process, start=1):
        ticker = (stock.get("ticker") or "").strip().upper()
        name = (stock.get("name") or "").strip() or ticker
        if not ticker:
            continue
        logger.info(f"[{i}/{len(tickers_to_process)}] {ticker} ({name})")
        tickers_list = _get_openai_related_tickers(
            ticker, name, valid_tickers, client, model=model, use_web_search=use_web_search
        )
        related[ticker] = tickers_list
        if tickers_list:
            logger.info(f"  -> {tickers_list}")
        # Save to stocks.related_tickers column
        try:
            supabase.table("stocks").update({"related_tickers": tickers_list}).eq("ticker", ticker).execute()
        except Exception as e:
            logger.warning(f"Failed to update stocks.related_tickers for {ticker}: {e}")
        time.sleep(args.delay)

    # Also write JSON file for config (RELATED_TICKERS_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(related, f, indent=2)

    logger.info(f"Updated stocks.related_tickers for {len(related)} tickers and wrote {out_path}")


if __name__ == "__main__":
    main()
