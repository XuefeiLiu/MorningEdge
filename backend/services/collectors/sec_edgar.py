"""
SEC EDGAR data collector for company filings.
Free public API, rate limit: 10 requests/second.
CIK lookup: uses hardcoded map first, then lazy-loads company_tickers.json once to avoid 429.

Task3 optimization: discover which tickers filed 10-K/10-Q via SEC daily index (form.idx)
so we only call the submissions API for those tickers, not all tickers.
"""
import asyncio
import httpx
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Set, Tuple
from hashlib import md5

from backend.config import (
    SEC_429_BACKOFF_SECONDS,
    SEC_EDGAR_BASE_URL,
    SEC_FILINGS_RECENT_LIMIT,
    SEC_RATE_LIMIT_DELAY,
)
from backend.models import SECFiling, ImpactLevel
from .base import BaseCollector

logger = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/daily-index"

# Form types we care about for pipeline Task3 (10-K, 10-Q only)
FILING_FORMS_UPDATE = frozenset({"10-K", "10-Q"})

# SEC form.idx: first 11 lines are header; then fixed-width: Company Name 0:62, Form Type 62:74, CIK 74:84 (10), Date 84:94 (10), File Name 94:
_FORM_IDX_HEADER_LINES = 11
_FORM_IDX_FORM_START = 62
_FORM_IDX_FORM_END = 74
_FORM_IDX_CIK_START = 74
_FORM_IDX_CIK_END = 84
_FORM_IDX_DATE_START = 84
_FORM_IDX_DATE_END = 94

# SEC form types and their impact levels
FORM_IMPACT_MAP = {
    "8-K": ImpactLevel.HIGH,      # Current report (material events)
    "10-K": ImpactLevel.HIGH,     # Annual report
    "10-Q": ImpactLevel.MEDIUM,   # Quarterly report
    "4": ImpactLevel.MEDIUM,      # Insider trading
    "13F": ImpactLevel.LOW,       # Institutional holdings
    "SC 13G": ImpactLevel.MEDIUM, # Beneficial ownership
    "SC 13D": ImpactLevel.HIGH,   # Activist investor
    "DEF 14A": ImpactLevel.LOW,   # Proxy statement
    "S-1": ImpactLevel.HIGH,      # IPO registration
    "424B": ImpactLevel.MEDIUM,   # Prospectus
}

# CIK mapping for common stocks (partial list). Others resolved via company_tickers.json (fetched once).
SYMBOL_TO_CIK: Dict[str, str] = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "AMZN": "0001018724",
    "META": "0001326801",
    "TSLA": "0001318605",
    "NVDA": "0001045810",
    "JPM": "0000019617",
    "V": "0001403161",
    "JNJ": "0000200406",
}

# Lazy-loaded full ticker->CIK map from company_tickers.json (one request per process to avoid 429)
_tickers_json_cache: Optional[Dict[str, str]] = None
_tickers_json_lock: Optional[asyncio.Lock] = None


def _get_tickers_lock() -> asyncio.Lock:
    global _tickers_json_lock
    if _tickers_json_lock is None:
        _tickers_json_lock = asyncio.Lock()
    return _tickers_json_lock


def _daily_index_url(filing_date: date) -> str:
    """Build SEC daily index form.idx URL for a given date (e.g. 2025/QTR4/form.20251231.idx)."""
    y = filing_date.year
    m = filing_date.month
    qtr = (m - 1) // 3 + 1
    dstr = filing_date.strftime("%Y%m%d")
    return f"{SEC_ARCHIVES_BASE}/{y}/QTR{qtr}/form.{dstr}.idx"


async def get_tickers_with_recent_filings(
    start_date: datetime,
    end_date: datetime,
    valid_tickers: Set[str],
    *,
    form_types: Tuple[str, ...] = ("10-K", "10-Q"),
) -> Set[str]:
    """
    Discover which of our tickers filed 10-K/10-Q in [start_date, end_date] by parsing SEC daily index.
    Returns only ticker symbols that are in valid_tickers and have at least one matching filing.
    This avoids calling the submissions API for every ticker; we only process tickers that actually filed.
    """
    if not valid_tickers:
        return set()
    form_set = frozenset(form_types)
    # Load ticker -> CIK and build CIK -> ticker for our tickers only
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "MorningEdge/1.0 (contact@example.com)", "Accept": "text/plain"},
    ) as client:
        ticker_to_cik: Dict[str, str] = {}
        try:
            await asyncio.sleep(SEC_RATE_LIMIT_DELAY)
            resp = await client.get(COMPANY_TICKERS_URL)
            resp.raise_for_status()
            data = resp.json()
            for entry in data.values():
                ticker = (entry.get("ticker") or "").strip().upper()
                if ticker and ticker in valid_tickers:
                    cik = str(entry.get("cik_str", "")).zfill(10)
                    ticker_to_cik[ticker] = cik
        except Exception as e:
            logger.warning(f"Could not load company_tickers for filing discovery: {e}")
            return set()
        cik_to_ticker = {cik: t for t, cik in ticker_to_cik.items()}
        if not cik_to_ticker:
            logger.warning(
                "Filing discovery: no CIKs resolved for valid_tickers (check company_tickers.json). valid_tickers count=%s",
                len(valid_tickers),
            )
            return set()
        logger.info(
            "Filing discovery: resolved %s/%s tickers to CIKs, scanning daily index %s to %s",
            len(cik_to_ticker),
            len(valid_tickers),
            start_date.date() if hasattr(start_date, "date") else start_date,
            end_date.date() if hasattr(end_date, "date") else end_date,
        )
        ciks_that_filed: Set[str] = set()
        start_d = start_date.date() if hasattr(start_date, "date") else start_date
        end_d = end_date.date() if hasattr(end_date, "date") else end_date
        current = start_d
        skipped_days = 0
        while current <= end_d:
            url = _daily_index_url(current)
            try:
                await asyncio.sleep(SEC_RATE_LIMIT_DELAY)
                r = await client.get(url)
                if r.status_code == 429:
                    await asyncio.sleep(SEC_429_BACKOFF_SECONDS)
                    continue
                r.raise_for_status()
                text = r.text
            except Exception as e:
                skipped_days += 1
                logger.info(
                    "SEC daily index %s: %s (index may not be published yet for recent days)",
                    current,
                    e,
                )
                current += timedelta(days=1)
                continue
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if i < _FORM_IDX_HEADER_LINES or len(line) < _FORM_IDX_DATE_END:
                    continue
                form_type = line[_FORM_IDX_FORM_START:_FORM_IDX_FORM_END].strip()
                if form_type not in form_set:
                    continue
                cik = line[_FORM_IDX_CIK_START:_FORM_IDX_CIK_END].strip().zfill(10)
                if cik in cik_to_ticker:
                    ciks_that_filed.add(cik)
            current += timedelta(days=1)

        if skipped_days:
            logger.info(
                "Filing discovery: skipped %s day(s); recent days may not have form.idx published yet (~10pm ET)",
                skipped_days,
            )
        return {cik_to_ticker[cik] for cik in ciks_that_filed}


class SECEdgarCollector(BaseCollector):
    """Collector for SEC EDGAR filings."""
    
    def __init__(self):
        super().__init__("sec_edgar")
        self.base_url = SEC_EDGAR_BASE_URL
        self.headers = {
            "User-Agent": "MorningEdge/1.0 (contact@example.com)",
            "Accept": "application/json"
        }
    
    async def collect(
        self,
        symbols: List[str],
        start_time: datetime,
        end_time: datetime
    ) -> List[SECFiling]:
        """Collect SEC filings for symbols within time window."""
        filings = []
        
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=self.headers) as client:
                for symbol in symbols:
                    try:
                        symbol_filings = await self._get_filings(
                            client, symbol, start_time, end_time
                        )
                        filings.extend(symbol_filings)
                    except Exception as e:
                        logger.error(f"Error fetching SEC filings for {symbol}: {e}")
        except Exception as e:
            logger.error(f"SEC collection failed: {e}")
        
        return filings
    
    async def _load_company_tickers_once(self, client: httpx.AsyncClient) -> Optional[Dict[str, str]]:
        """Fetch company_tickers.json once per process and return symbol->CIK map. Avoids 429 by not calling per ticker."""
        global _tickers_json_cache
        if _tickers_json_cache is not None:
            return _tickers_json_cache
        async with _get_tickers_lock():
            if _tickers_json_cache is not None:
                return _tickers_json_cache
            for attempt in range(3):  # 0, 1, 2 = up to 3 tries on 429
                try:
                    await asyncio.sleep(SEC_RATE_LIMIT_DELAY)
                    response = await client.get(COMPANY_TICKERS_URL)
                    response.raise_for_status()
                    data = response.json()
                    cache: Dict[str, str] = {}
                    for entry in data.values():
                        ticker = (entry.get("ticker") or "").strip().upper()
                        if ticker:
                            cik = str(entry.get("cik_str", "")).zfill(10)
                            cache[ticker] = cik
                    _tickers_json_cache = cache
                    logger.info(f"Loaded SEC company_tickers.json ({len(cache)} symbols) for CIK lookup")
                    return _tickers_json_cache
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < 2:
                        wait = SEC_429_BACKOFF_SECONDS
                        logger.warning(f"SEC 429 on company_tickers.json, waiting {wait}s before retry ({attempt + 1}/2)")
                        await asyncio.sleep(wait)
                        continue
                    logger.warning(f"Could not load company_tickers.json: {e}")
                    return None
                except Exception as e:
                    logger.warning(f"Could not load company_tickers.json: {e}")
                    return None
            return None

    async def _get_cik(self, client: httpx.AsyncClient, symbol: str) -> Optional[str]:
        """Get CIK number for a symbol. Uses hardcoded map first, then full ticker list (fetched once)."""
        sym = symbol.strip().upper()
        if not sym:
            return None
        if sym in SYMBOL_TO_CIK:
            return SYMBOL_TO_CIK[sym]
        full_map = await self._load_company_tickers_once(client)
        if full_map and sym in full_map:
            cik = full_map[sym]
            SYMBOL_TO_CIK[sym] = cik
            return cik
        return None
    
    async def _get_filings(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[SECFiling]:
        """Get recent filings for a symbol."""
        cik = await self._get_cik(client, symbol)
        
        if not cik:
            logger.warning(f"No CIK found for {symbol}, skipping SEC filings")
            return []
        
        # Rate-limit: delay before submissions request so we don't burst with filing fetches
        await asyncio.sleep(SEC_RATE_LIMIT_DELAY)
        url = f"{self.base_url}/submissions/CIK{cik}.json"
        
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            logger.error(f"Error fetching submissions for {symbol}: {e}")
            return []
        
        filings = []
        recent = data.get("filings", {}).get("recent", {})
        
        if not recent:
            return filings
        
        form_types = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])
        
        limit = min(len(form_types), SEC_FILINGS_RECENT_LIMIT)
        for i in range(limit):
            try:
                # Parse filing date
                date_str = filing_dates[i] if i < len(filing_dates) else None
                if not date_str:
                    continue
                    
                filed_date = datetime.strptime(date_str, "%Y-%m-%d")
                filed_d = filed_date.date()
                start_d = start_time.date() if hasattr(start_time, "date") else start_time
                end_d = end_time.date() if hasattr(end_time, "date") else end_time
                # Compare dates only so filings on start_d/end_d are included
                if filed_d < start_d or filed_d > end_d:
                    continue
                
                form_type = form_types[i] if i < len(form_types) else "Unknown"
                accession = accession_numbers[i] if i < len(accession_numbers) else ""
                primary_doc = primary_documents[i] if i < len(primary_documents) else ""
                description = descriptions[i] if i < len(descriptions) else ""
                
                # Build filing URL
                accession_clean = accession.replace("-", "")
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession_clean}/{primary_doc}"
                
                # Determine impact level
                impact = ImpactLevel.LOW
                for form_prefix, level in FORM_IMPACT_MAP.items():
                    if form_type.startswith(form_prefix):
                        impact = level
                        break
                
                filing_id = md5(f"{symbol}{accession}".encode()).hexdigest()[:12]
                
                filings.append(SECFiling(
                    id=f"sec_{filing_id}",
                    symbol=symbol,
                    form_type=form_type,
                    filed_date=filed_date,
                    description=description or f"{form_type} Filing",
                    url=filing_url,
                    impact_level=impact,
                    accession_number=accession or None,
                ))
            except Exception as e:
                logger.error(f"Error parsing filing {i} for {symbol}: {e}")
                continue
        
        return filings
