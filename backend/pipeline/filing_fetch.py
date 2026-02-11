"""
Fetch full text from SEC 10-K/10-Q primary document (HTML).

Uses HTML parsing and table extraction logic rewritten from table.py:
extract table + surrounding context and represent as markdown/plain text for chunking.
Does not import table.py (which targets PDFs); this module is for SEC HTML only.
"""
import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from backend.config import SEC_429_BACKOFF_SECONDS, SEC_FETCH_TIMEOUT, SEC_RATE_LIMIT_DELAY

logger = logging.getLogger(__name__)

SEC_429_MAX_RETRIES = 2

SEC_HEADERS = {
    "User-Agent": "MorningEdge/1.0 (contact@example.com)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip, deflate",
}


def _html_table_to_markdown(table: Tag) -> str:
    """Convert a single HTML <table> to markdown-style text (rewritten from table.py pattern)."""
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"]):
            cells.append(cell.get_text(separator=" ", strip=True).replace("\n", " "))
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    # Simple markdown: header row, then separator, then body
    lines = []
    for i, row in enumerate(rows):
        lines.append(" | ".join(row))
        if i == 0 and len(rows) > 1:
            lines.append(" | ".join(["---"] * len(row)))
    return "\n".join(lines)


def _get_table_context(table: Tag) -> str:
    """Get preceding sibling text (e.g. section heading) for table context."""
    context_parts = []
    prev = table.find_previous_sibling()
    for _ in range(3):
        if prev is None:
            break
        if isinstance(prev, Tag):
            t = prev.get_text(separator=" ", strip=True)
            if t and len(t) < 500:
                context_parts.append(t)
        prev = prev.find_previous_sibling() if prev else None
    return " ".join(reversed(context_parts)) if context_parts else ""


def _merge_text_and_tables(soup: BeautifulSoup) -> str:
    """
    Produce one full-document text: body text with tables represented as markdown blocks.
    Rewritten from table.py: extract table + surrounding context, replace <table> in place, then get_text.
    """
    body = soup.find("body")
    if not body:
        return soup.get_text(separator="\n", strip=True)
    # Remove script/style
    for tag in body.find_all(["script", "style"]):
        tag.decompose()
    # Replace each table with markdown (context + table) so document order is preserved
    for table in body.find_all("table"):
        md = _html_table_to_markdown(table)
        if not md or len(md.strip()) < 10:
            table.replace_with("\n\n")
            continue
        context = _get_table_context(table)
        block = "\n\n"
        if context:
            block += context + "\n\n"
        block += md + "\n\n"
        table.replace_with(block)
    text = body.get_text(separator="\n", strip=True)
    full = re.sub(r"\n{3,}", "\n\n", text)
    return full.strip()


def extract_text_from_html(html: str) -> str:
    """
    Parse SEC filing HTML and return plain text suitable for chunking.
    Tables are converted to markdown-style text with surrounding context (rewritten from table.py).
    """
    soup = BeautifulSoup(html, "html.parser")
    return _merge_text_and_tables(soup)


async def fetch_filing_full_text(
    url: str,
    *,
    timeout: float = SEC_FETCH_TIMEOUT,
    rate_limit_delay: float = SEC_RATE_LIMIT_DELAY,
    backoff_seconds: int = SEC_429_BACKOFF_SECONDS,
) -> Optional[str]:
    """
    Fetch SEC primary document HTML and return extracted full text (primary only, no exhibits).
    Respects SEC rate limit via rate_limit_delay. Retries on 429 with backoff.
    """
    await asyncio.sleep(rate_limit_delay)
    html = None
    for attempt in range(SEC_429_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=SEC_HEADERS) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
            break
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < SEC_429_MAX_RETRIES:
                logger.warning(f"SEC 429 for filing, waiting {backoff_seconds}s before retry ({attempt + 1}/{SEC_429_MAX_RETRIES})")
                await asyncio.sleep(backoff_seconds)
                continue
            logger.warning(f"Failed to fetch filing from {url[:80]}...: {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch filing from {url[:80]}...: {e}")
            return None
    if html is None:
        return None
    if not html or len(html) < 100:
        logger.warning(f"Empty or tiny response from {url[:80]}...")
        return None
    # Cap size for very large filings (e.g. 10-K with huge tables)
    max_chars = 2_000_000
    if len(html) > max_chars:
        html = html[:max_chars] + "</body></html>"
    try:
        text = extract_text_from_html(html)
    except Exception as e:
        logger.warning(f"Failed to parse HTML from {url[:80]}...: {e}")
        return None
    if not text or len(text.strip()) < 50:
        logger.warning(f"Extracted text too short from {url[:80]}...")
        return None
    return text
