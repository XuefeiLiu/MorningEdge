"""
Store/embed data: full Task1 — macro news, macro digest (optional), collect+store news with embeddings, filing update (optional).
Single module used by pipeline.py (Task1) and overnight pipeline runner.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from supabase import Client
from openai import AsyncOpenAI

from backend.config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    PIPELINE_RUN_MACRO_DIGEST,
    PIPELINE_TICKER_CONCURRENCY,
    PIPELINE_RUN_FILING_UPDATE,
    FILING_UPDATE_DAYS,
    FILING_FORMS,
)
from backend.storage.supabase_client import get_supabase_client
from backend.storage.stocks_query import get_all_stocks
from backend.pipeline.news_collection import collect_todays_news, store_news_with_embeddings
from backend.storage.macro_articles_main import collect_macro_news
from backend.services.collectors.sec_edgar import SECEdgarCollector
from backend.pipeline.filing_fetch import fetch_filing_full_text
from backend.pipeline.filing_chunking import chunk_filing_text
from backend.storage.filing_store import upsert_sec_filing, store_filing_chunks

logger = logging.getLogger(__name__)


async def _process_filing_update(supabase: Client, filing: Any) -> int:
    """Fetch full text, chunk, store for one filing. Returns chunks stored (0 on skip/fail)."""
    ticker = filing.symbol.strip().upper()
    form_type = filing.form_type or ""
    if form_type not in FILING_FORMS:
        return 0
    accession = getattr(filing, "accession_number", None) or ""
    if not accession:
        return 0
    try:
        existing = (
            supabase.table("sec_filings")
            .select("id")
            .eq("ticker", ticker)
            .eq("accession_number", accession)
            .limit(1)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            return 0
    except Exception:
        pass
    full_text = await fetch_filing_full_text(filing.url)
    if not full_text:
        return 0
    filed_date_str = (
        filing.filed_date.strftime("%Y-%m-%d")
        if hasattr(filing.filed_date, "strftime")
        else str(filing.filed_date)[:10]
    )
    chunks = chunk_filing_text(full_text, ticker, form_type, filed_date_str)
    if not chunks:
        return 0
    filing_id = await upsert_sec_filing(
        supabase,
        ticker=ticker,
        form_type=form_type,
        filed_date=filed_date_str,
        accession_number=accession,
        url=filing.url,
        primary_document=None,
    )
    if filing_id is None:
        return 0
    return await store_filing_chunks(supabase, filing_id, ticker, chunks, accession_number=accession)


async def _run_filing_update(
    supabase: Client,
    tickers: List[str],
    start_date: datetime,
    end_date: datetime,
) -> Dict[str, int]:
    """Fetch new 10-K/10-Q in window, chunk, embed, store. Returns stats."""
    stats = {"filings_processed": 0, "chunks_stored": 0}
    collector = SECEdgarCollector()
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        logger.info("[%s/%s] %s...", i + 1, total, ticker)
        try:
            filings = await collector.collect(
                symbols=[ticker],
                start_time=start_date,
                end_time=end_date,
            )
        except Exception as e:
            logger.warning("Filing update: SEC collect failed for %s: %s", ticker, e)
            continue
        filings_10k_10q = [f for f in filings if f.form_type in FILING_FORMS]
        ticker_stored = 0
        ticker_chunks = 0
        for filing in filings_10k_10q:
            stored = await _process_filing_update(supabase, filing)
            if stored > 0:
                ticker_stored += 1
                ticker_chunks += stored
                stats["filings_processed"] += 1
                stats["chunks_stored"] += stored
        logger.info(
            "  %s: %s filings in window, %s new stored, %s chunks",
            ticker,
            len(filings_10k_10q),
            ticker_stored,
            ticker_chunks,
        )
    return stats


async def _collect_and_store_one_ticker(
    supabase: Client,
    ticker: str,
    ticker_sem: asyncio.Semaphore,
    index: int,
    total: int,
    *,
    include_gemini: bool = False,
    include_alpha_vantage: bool = True,
    include_massive: bool = True,
) -> Dict[str, Any]:
    """Collect and store news for one ticker (no storyline processing)."""
    async with ticker_sem:
        stats = {
            "tickers_processed": 0,
            "articles_collected": 0,
            "articles_stored": 0,
            "failed_tickers": [],
        }
        try:
            logger.info("[%d/%d] Collect+store for %s...", index, total, ticker)
            stats["tickers_processed"] = 1
            news_items = await collect_todays_news(
                ticker,
                supabase=supabase,
                include_gemini=include_gemini,
                include_alpha_vantage=include_alpha_vantage,
                include_massive=include_massive,
            )
            stats["articles_collected"] = len(news_items)
            if not news_items:
                return stats
            stored_articles = await store_news_with_embeddings(supabase, ticker, news_items)
            stats["articles_stored"] = len(stored_articles)
            return stats
        except Exception as e:
            logger.error("Collect+store failed for %s: %s", ticker, e)
            stats["failed_tickers"] = [ticker]
            return stats


async def run_store_embed_data(
    supabase: Optional[Client] = None,
    tickers: Optional[List[str]] = None,
    *,
    include_gemini: bool = False,
    include_alpha_vantage: bool = True,
    include_massive: bool = True,
    concurrency: int = PIPELINE_TICKER_CONCURRENCY,
    run_macro: bool = True,
    run_macro_digest: Optional[bool] = None,
    run_filing_update: Optional[bool] = None,
    valid_tickers: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Full Task1: macro news, optional macro digest, collect+store news with embeddings, optional filing update.
    If tickers is None, use all stocks from the database.
    valid_tickers: set of ticker strings for filing update (if None, derived from tickers).
    Returns stats: macro_articles_stored, macro_digest_raw, macro_digest_briefs, macro_daily_summary,
    tickers_processed, articles_collected, articles_stored, filings_processed, chunks_stored, failed_tickers.
    """
    if supabase is None:
        supabase = get_supabase_client()
    if run_macro_digest is None:
        run_macro_digest = PIPELINE_RUN_MACRO_DIGEST
    if run_filing_update is None:
        run_filing_update = PIPELINE_RUN_FILING_UPDATE

    stats: Dict[str, Any] = {
        "macro_articles_stored": 0,
        "macro_digest_raw": 0,
        "macro_digest_briefs": 0,
        "macro_daily_summary": 0,
        "tickers_processed": 0,
        "articles_collected": 0,
        "articles_stored": 0,
        "filings_processed": 0,
        "chunks_stored": 0,
        "failed_tickers": [],
    }

    now = datetime.now(timezone.utc)
    macro_start = now - timedelta(hours=24)
    macro_end = now

    # Resolve tickers once (needed for both stock news and filing update)
    if tickers is None:
        stocks = get_all_stocks(supabase)
        tickers = [(s.get("ticker") or "").strip() for s in stocks if (s.get("ticker") or "").strip()]
    if not tickers:
        logger.warning("No tickers for store_embed_data")
        return stats

    vticks = valid_tickers if valid_tickers is not None else {t.upper() for t in tickers}
    ticker_list = list(vticks)
    filing_start = now - timedelta(days=FILING_UPDATE_DAYS)
    filing_end_dt = now

    async def _do_macro() -> Dict[str, Any]:
        out = {"macro_articles_stored": 0}
        if not run_macro:
            return out
        try:
            macro_results = await collect_macro_news(macro_start, macro_end)
            out["macro_articles_stored"] = macro_results.get("inserted_count", 0)
            logger.info("Macro news: %s articles stored for last 24h", out["macro_articles_stored"])
        except Exception as e:
            logger.warning("Macro news collection failed: %s", e)
        return out

    async def _do_filing() -> Dict[str, Any]:
        out = {"filings_processed": 0, "chunks_stored": 0}
        if not run_filing_update:
            return out
        try:
            logger.info(
                "Filing update (last %sd): checking %s tickers via submissions API",
                FILING_UPDATE_DAYS,
                len(ticker_list),
            )
            filing_stats = await _run_filing_update(
                supabase, ticker_list, filing_start, filing_end_dt
            )
            out["filings_processed"] = filing_stats.get("filings_processed", 0)
            out["chunks_stored"] = filing_stats.get("chunks_stored", 0)
            logger.info(
                "Filing update: %s new filings, %s chunks stored",
                out["filings_processed"],
                out["chunks_stored"],
            )
        except Exception as e:
            logger.warning("Filing update failed: %s", e)
        return out

    async def _do_stock_news() -> Dict[str, Any]:
        out = {"tickers_processed": 0, "articles_collected": 0, "articles_stored": 0, "failed_tickers": []}
        ticker_sem = asyncio.Semaphore(concurrency)
        total = len(tickers)
        tasks = [
            _collect_and_store_one_ticker(
                supabase,
                t,
                ticker_sem,
                i + 1,
                total,
                include_gemini=include_gemini,
                include_alpha_vantage=include_alpha_vantage,
                include_massive=include_massive,
            )
            for i, t in enumerate(tickers)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error("Store+embed failed for %s: %s", tickers[i], r)
                out["failed_tickers"].append(tickers[i])
                continue
            out["tickers_processed"] += r.get("tickers_processed", 0)
            out["articles_collected"] += r.get("articles_collected", 0)
            out["articles_stored"] += r.get("articles_stored", 0)
            out["failed_tickers"].extend(r.get("failed_tickers", []))
        logger.info(
            "Store/embed done: tickers=%s articles_collected=%s articles_stored=%s failed=%s",
            out["tickers_processed"],
            out["articles_collected"],
            out["articles_stored"],
            len(out["failed_tickers"]),
        )
        return out

    # Run macro, filing update, and stock news in parallel
    logger.info("Running macro news, filing update, and stock news in parallel")
    macro_result, filing_result, stock_result = await asyncio.gather(
        _do_macro(),
        _do_filing(),
        _do_stock_news(),
    )
    stats["macro_articles_stored"] = macro_result.get("macro_articles_stored", 0)
    stats["filings_processed"] = filing_result.get("filings_processed", 0)
    stats["chunks_stored"] = filing_result.get("chunks_stored", 0)
    stats["tickers_processed"] = stock_result.get("tickers_processed", 0)
    stats["articles_collected"] = stock_result.get("articles_collected", 0)
    stats["articles_stored"] = stock_result.get("articles_stored", 0)
    stats["failed_tickers"] = stock_result.get("failed_tickers", [])

    # Macro digest runs after macro news (depends on macro data in DB)
    if run_macro_digest:
        as_of_date = macro_end.date()
        try:
            from backend.macro.collect_raw import collect_and_save_raw

            raw_count = await asyncio.to_thread(collect_and_save_raw, as_of_date, supabase)
            stats["macro_digest_raw"] = raw_count
            logger.info("Macro digest raw: %s items for %s", raw_count, as_of_date)

            from backend.macro.synthesis import synthesize_all_topics
            from backend.macro.daily_summary import synthesize_daily_summary

            if OPENAI_API_KEY:
                llm = AsyncOpenAI(api_key=OPENAI_API_KEY)
                model = OPENAI_MODEL
            else:
                llm = model = None
            if llm and model:
                brief_count = await synthesize_all_topics(
                    as_of_date, supabase=supabase, llm_client=llm, llm_model=model
                )
                stats["macro_digest_briefs"] = brief_count
                logger.info("Macro digest briefs: %s for %s", brief_count, as_of_date)
                daily_summary_id = await synthesize_daily_summary(
                    as_of_date, supabase=supabase, llm_client=llm, llm_model=model
                )
                stats["macro_daily_summary"] = 1 if daily_summary_id else 0
                if daily_summary_id:
                    logger.info("Macro daily summary saved for %s", as_of_date)
            else:
                logger.warning(
                    "Macro digest synthesis skipped: set OPENAI_API_KEY"
                )
        except Exception as e:
            logger.warning("Macro digest failed: %s", e, exc_info=True)

    return stats
