"""
Long story service: create and update long_stories.

When a new story deserves_long_story, we either merge into an existing long story
(by embedding similarity) or create a new long story. Long stories live in long_stories and
long_story_article_links only.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from hashlib import md5
from typing import Any, Dict, List, Optional, Tuple

from supabase import Client
from openai import AsyncOpenAI

from backend.config import (
    LONG_STORY_SIMILARITY_THRESHOLD,
    MAX_LONG_STORY_ARTICLES,
    MIN_LONG_STORY_ARTICLES,
    OPENAI_API_KEY,
    OPENAI_MODEL,
)
from backend.services.embedding_service import get_embedding_service
from backend.storage.news_articles_save import _string_id_to_bigint

logger = logging.getLogger(__name__)

RELATION_LABELS = {"CONTINUATION", "ESCALATION", "CONTRADICTION", "RESOLUTION", "NEW_ANGLE", "UNRELATED", "CONTEXT"}


def _get_client_and_model(client: AsyncOpenAI, model: Optional[str] = None) -> Tuple[AsyncOpenAI, str]:
    """Return (client, model). If model is provided, use it. Else use OPENAI_MODEL."""
    if model is not None:
        return client, model
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when model is not passed.")
    return client, OPENAI_MODEL


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def find_similar_long_story(
    supabase: Client,
    ticker: str,
    embedding: List[float],
    threshold: float = None,
) -> Optional[Dict[str, Any]]:
    """
    Return the most similar long story for this ticker by embedding cosine similarity,
    or None if none above threshold. Expects long_stories.embedding to be stored as list or vector.
    """
    if not embedding:
        return None
    thresh = threshold if threshold is not None else LONG_STORY_SIMILARITY_THRESHOLD
    try:
        result = (
            supabase.table("long_stories")
            .select("id, ticker, title, canonical_theme, summary, embedding")
            .eq("ticker", ticker.strip().upper())
            .not_.is_("embedding", "null")
            .execute()
        )
    except Exception as e:
        if "does not exist" in str(e).lower() or "column" in str(e).lower():
            return None
        raise
    rows = result.data or []
    if not rows:
        return None
    best = None
    best_sim = thresh
    for r in rows:
        emb = r.get("embedding")
        if emb is None:
            continue
        if isinstance(emb, str):
            try:
                import json
                emb = json.loads(emb) if emb.startswith("[") else emb
            except Exception:
                continue
        if not isinstance(emb, list):
            continue
        sim = _cosine_similarity(embedding, emb)
        if sim > best_sim:
            best_sim = sim
            best = r
    return best


async def add_article_to_long_story(
    supabase: Client,
    long_story_id: int,
    long_story_ticker: str,
    article_id: int,
    article_ticker: str,
    relation_type: str = "CONTEXT",
) -> bool:
    """
    Link article to long story. If total links exceed MAX_LONG_STORY_ARTICLES, remove oldest
    (by latest_update_at) to keep cap. Ensures at least 2 distinct months among linked articles.
    Returns True if link was added or already existed.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("long_story_article_links").insert({
            "long_story_id": long_story_id,
            "article_id": article_id,
            "relation_type": relation_type,
            "article_ticker": (article_ticker or "").strip().upper(),
            "long_story_ticker": (long_story_ticker or "").strip().upper(),
            "initial_created": now_iso,
            "latest_update_at": now_iso,
        }).execute()
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "unique" in err or "conflict" in err:
            return True
        logger.warning("add_article_to_long_story insert failed: %s", e)
        return False

    # Enforce cap: count links and if > MAX, delete oldest (by latest_update_at)
    try:
        links = (
            supabase.table("long_story_article_links")
            .select("article_id, latest_update_at")
            .eq("long_story_id", long_story_id)
            .order("latest_update_at", desc=False)
            .execute()
        )
        data = links.data or []
        if len(data) <= MAX_LONG_STORY_ARTICLES:
            return True
        # Delete oldest (first) links until we're at cap
        to_remove = len(data) - MAX_LONG_STORY_ARTICLES
        for i in range(to_remove):
            row = data[i]
            supabase.table("long_story_article_links").delete().eq("long_story_id", long_story_id).eq("article_id", row["article_id"]).execute()
        logger.info("Capped long_story %s links to %d (removed %d oldest)", long_story_id, MAX_LONG_STORY_ARTICLES, to_remove)
    except Exception as e:
        logger.debug("Cap check failed: %s", e)
    return True


async def refresh_long_story_content(
    supabase: Client,
    long_story_id: int,
    llm_client: AsyncOpenAI,
    model: Optional[str] = None,
) -> bool:
    """
    Refresh a long story's title, canonical_theme, summary, and embedding from its linked articles.
    Fetches linked articles (newest first), asks LLM for updated title/theme/summary, then updates
    the long_stories row and recomputes embedding. Returns True if updated successfully.
    """

    try:
        row = (
            supabase.table("long_stories")
            .select("id, ticker, title, canonical_theme, summary")
            .eq("id", long_story_id)
            .limit(1)
            .execute()
        )
        data = (row.data or [])
        if not data:
            return False
        story = data[0]
        ticker = (story.get("ticker") or "").strip().upper()
        current_title = (story.get("title") or "").strip()
        current_theme = (story.get("canonical_theme") or "").strip()
        current_summary = (story.get("summary") or "").strip()

        links = (
            supabase.table("long_story_article_links")
            .select("article_id, latest_update_at")
            .eq("long_story_id", long_story_id)
            .order("latest_update_at", desc=True)
            .limit(MAX_LONG_STORY_ARTICLES)
            .execute()
        )
        link_data = links.data or []
        if not link_data:
            return False
        article_ids = [r["article_id"] for r in link_data if r.get("article_id") is not None]
        if not article_ids:
            return False

        arts = (
            supabase.table("news_articles")
            .select("id, title, summary, published_at")
            .in_("id", article_ids)
            .execute()
        )
        arts_list = arts.data or []
        id_to_art = {a["id"]: a for a in arts_list}
        ordered_arts = [id_to_art[aid] for aid in article_ids if aid in id_to_art]
        if not ordered_arts:
            return False

        articles_context = ""
        for a in ordered_arts:
            title = (a.get("title") or "")
            summary = (a.get("summary") or title)
            pub = a.get("published_at", "")
            articles_context += f"ID {a.get('id')}: {title}\n  Summary: {summary}\n  Date: {pub}\n\n"

        prompt = f"""You are a financial news analyst. This is an existing long-form storyline (ticker: {ticker}). We just added a new article to it. Produce an updated title, theme, and summary that reflect the full narrative across all linked articles (newest first).

CURRENT TITLE: {current_title}
CURRENT THEME: {current_theme}
CURRENT SUMMARY: {current_summary}

LINKED ARTICLES (newest first):
{articles_context}

Return a single JSON object with: "title", "theme", "summary". Keep title and theme concise (e.g. under 200 chars). Summary can be longer. Return only the JSON object."""

        llm_client, llm_model = _get_client_and_model(llm_client, model or OPENAI_MODEL)
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": "You output only valid JSON with keys: title, theme, summary. No other text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_completion_tokens=2000,
        )
        raw = (response.choices[0].message.content or "").strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)
        parsed = json.loads(raw)
        new_title = (parsed.get("title") or "").strip()[:200]
        new_theme = (parsed.get("theme")  or "").strip()[:200]
        new_summary = (parsed.get("summary")  or "").strip()
        if not (new_title and new_theme and new_summary):
            logger.info("refresh_long_story_content: LLM returned no title, theme, or summary, skip")
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("long_stories").update({
            "title": new_title,
            "canonical_theme": new_theme,
            "summary": new_summary,
            "last_updated_at": now_iso,
        }).eq("id", long_story_id).execute()

        text_for_emb = f"{new_title}\n{new_theme}\n{new_summary}".strip()
        if text_for_emb:
            emb_svc = get_embedding_service()
            emb = await emb_svc.get_embeddings([text_for_emb])
            if emb is not None and len(emb) > 0:
                vec = emb[0].tolist() if hasattr(emb[0], "tolist") else list(emb[0])
                supabase.table("long_stories").update({"embedding": vec}).eq("id", long_story_id).execute()
        logger.info("Refreshed long_story id=%s title/summary/embedding", long_story_id)
        return True
    except (json.JSONDecodeError, KeyError, Exception) as e:
        logger.warning("refresh_long_story_content failed for long_story %s: %s", long_story_id, e)
        return False


async def create_long_story(
    supabase: Client,
    ticker: str,
    historical_articles: List[Dict[str, Any]],
    llm_client: AsyncOpenAI,
    model: Optional[str] = None,
) -> Tuple[Optional[int], List[int], str, List[str]]:
    """
    Create a new long story in long_stories with links in long_story_article_links.
    Uses historical_articles as the full set of candidate articles; LLM selects used_article_ids.
    Enforces MIN_LONG_STORY_ARTICLES and MAX_LONG_STORY_ARTICLES; articles must span at least 2 months.
    Returns (long_story_id or None, useful_article_ids, relation_type, used_article_relation_types).
    """

    articles_context = ""
    for h in (historical_articles or [])[:20]:
        hid = h.get("id")
        if hid is None:
            continue
        htitle = h.get("title", "")
        hsum = (h.get("summary") or htitle)[:500]
        hdate = h.get("published_at", "")
        articles_context += f"Article ID {hid}: {htitle}\n  Summary: {hsum}\n  Date: {hdate}\n\n"

    prompt = f"""You are a financial news analyst. Given the following articles, produce a LONG-FORM narrative storyline (one clear topic). Every article you include must be about that topic.

ARTICLES:
{articles_context}

Return a single JSON object with: "title", "theme", "summary", "relationship", "used_article_ids" (array of article IDs from the list above, same topic only), "relationships" (array same length as used_article_ids). Use relationship and relationships from: CONTINUATION, ESCALATION, CONTRADICTION, RESOLUTION, NEW_ANGLE, UNRELATED, CONTEXT. Exclude UNRELATED from used_article_ids.

Example:
{{"title": "Tesla Margin Pressure and Price War Narrative", "theme": "EV pricing and profitability evolution", "summary": "Tesla's shift toward volume over margin has defined the EV narrative over the past year. Initial price cuts in key markets were followed by mixed quarterly results and ongoing competition from legacy automakers. The storyline continued with further adjustments to product mix and geographic focus. Over subsequent quarters, the theme of demand elasticity and cost reduction remained central...", "relationship": "CONTINUATION", "used_article_ids": [101, 102, 103, 104], "relationships": ["CONTEXT", "CONTINUATION", "ESCALATION", "CONTINUATION"]}}

Return only the JSON object."""

    llm_client, llm_model = _get_client_and_model(llm_client, model or OPENAI_MODEL)
    historical_ids = {h.get("id") for h in (historical_articles or []) if h.get("id")}

    story_title = ""
    canonical_theme = ""
    long_summary = ""
    relation_type = "CONTEXT"
    useful_article_ids: List[int] = []
    used_article_relation_types: List[str] = []

    try:
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": "You output only valid JSON with keys: title, theme, summary, relationship, used_article_ids, relationships. No other text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_completion_tokens=2000,
        )
        raw = (response.choices[0].message.content or "").strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)
        data = json.loads(raw)
        story_title = (data.get("title") or "")[:200]
        canonical_theme = (data.get("theme") or "").strip()[:200]
        long_summary = (data.get("summary") or "").strip()
        if not (story_title.strip() and canonical_theme.strip() and long_summary.strip()):
            logger.info("create_long_story: LLM returned no title, theme, or summary, skip")
            return (None, useful_article_ids, relation_type, used_article_relation_types)
        rel = (data.get("relationship") or "CONTEXT").strip().upper().rstrip(".,;")
        if rel in RELATION_LABELS:
            relation_type = rel
        seen_aids: set = set()
        for aid in data.get("used_article_ids") or []:
            if isinstance(aid, int) and aid in historical_ids and aid not in seen_aids:
                useful_article_ids.append(aid)
                seen_aids.add(aid)
        raw_rels = data.get("relationships") or []
        if isinstance(raw_rels, list) and len(raw_rels) >= len(useful_article_ids):
            used_article_relation_types = [r.strip().upper().rstrip(".,;") if isinstance(r, str) else "CONTEXT" for r in raw_rels[: len(useful_article_ids)]]
            used_article_relation_types = [r if r in RELATION_LABELS else "CONTEXT" for r in used_article_relation_types]
        else:
            used_article_relation_types = ["CONTEXT"] * len(useful_article_ids)
        filtered = [(aid, used_article_relation_types[i] if i < len(used_article_relation_types) else "CONTEXT") for i, aid in enumerate(useful_article_ids) if (used_article_relation_types[i] if i < len(used_article_relation_types) else "CONTEXT") != "UNRELATED"]
        useful_article_ids = [a for a, _ in filtered]
        used_article_relation_types = [r for _, r in filtered]
    except (json.JSONDecodeError, KeyError, Exception) as e:
        logger.warning("create_long_story LLM parse failed: %s", e)
        used_article_relation_types = ["CONTEXT"] * len(useful_article_ids)

    if len(useful_article_ids) < MIN_LONG_STORY_ARTICLES:
        logger.info("create_long_story: only %d articles, need >= %d", len(useful_article_ids), MIN_LONG_STORY_ARTICLES)
        return (None, useful_article_ids, relation_type, used_article_relation_types)

    # Enforce max and at least 2 months
    try:
        arts_with_dates = []
        for aid in useful_article_ids:
            art = next((a for a in (historical_articles or []) if a.get("id") == aid), None)
            pub = art.get("published_at") if art else None
            month = None
            if pub:
                try:
                    dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00")) if isinstance(pub, str) else pub
                    month = dt.strftime("%Y-%m")
                except (TypeError, ValueError):
                    pass
            arts_with_dates.append((aid, month))
        months = {m for _, m in arts_with_dates if m}
        if len(months) < 3:
            logger.info("create_long_story: articles do not span 3 months, skip")
            return (None, useful_article_ids, relation_type, used_article_relation_types)
        if len(useful_article_ids) > MAX_LONG_STORY_ARTICLES:
            useful_article_ids = useful_article_ids[:MAX_LONG_STORY_ARTICLES]
            used_article_relation_types = used_article_relation_types[:MAX_LONG_STORY_ARTICLES]
    except Exception as e:
        logger.debug("Month/max filter failed: %s", e)

    # ID is derived from ticker + canonical_theme only (not article IDs) so the same
    # theme always maps to the same long_story row regardless of which articles RAG returns.
    seed = f"{ticker.upper()}_long_{(canonical_theme or '').lower().strip()}"
    string_id = f"longstory_{md5(seed.encode('utf-8')).hexdigest()[:12]}"
    long_story_db_id = _string_id_to_bigint(string_id)

    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "id": long_story_db_id,
        "ticker": ticker.upper(),
        "title": story_title or canonical_theme or "",
        "canonical_theme": canonical_theme or "",
        "summary": long_summary,
        "impact_level": "high",
        "created_at": now_iso,
        "last_updated_at": now_iso,
    }

    try:
        supabase.table("long_stories").insert(row).execute()
    except Exception as e:
        err = str(e).lower()
        if "duplicate" in err or "unique" in err or "conflict" in err:
            try:
                existing = supabase.table("long_stories").select("id").eq("id", long_story_db_id).limit(1).execute()
                if existing.data and len(existing.data) > 0:
                    return (long_story_db_id, useful_article_ids, relation_type, used_article_relation_types)
            except Exception:
                pass
        if "column" in err or "impact_level" in err or "impact_score" in err:
            try:
                row_fallback = {k: v for k, v in row.items() if k not in ("impact_level", "impact_score")}
                supabase.table("long_stories").insert(row_fallback).execute()
            except Exception:
                logger.warning("create_long_story insert failed: %s", e)
                return (None, useful_article_ids, relation_type, used_article_relation_types)
        else:
            logger.warning("create_long_story insert failed: %s", e)
            return (None, useful_article_ids, relation_type, used_article_relation_types)

    # Insert links
    article_ticker_map: Dict[int, str] = {}
    try:
        arts = supabase.table("news_articles").select("id, ticker").in_("id", useful_article_ids).execute()
        for r in (arts.data or []):
            if r.get("id") is not None:
                article_ticker_map[int(r["id"])] = (r.get("ticker") or "").strip().upper()
    except Exception:
        pass
    ticker_upper = ticker.strip().upper()
    link_rows = []
    for i, aid in enumerate(useful_article_ids):
        link_rows.append({
            "long_story_id": long_story_db_id,
            "article_id": aid,
            "relation_type": used_article_relation_types[i] if i < len(used_article_relation_types) else "CONTEXT",
            "article_ticker": article_ticker_map.get(aid, ticker_upper),
            "long_story_ticker": ticker_upper,
            "initial_created": now_iso,
            "latest_update_at": now_iso,
        })
    for lr in link_rows:
        try:
            supabase.table("long_story_article_links").insert(lr).execute()
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "unique" in err or "conflict" in err:
                continue
            logger.warning("create_long_story link insert failed for article %s: %s", lr.get("article_id"), e)

    logger.info("Created long_story id=%s ticker=%s links=%d", long_story_db_id, ticker, len(link_rows))
    return (long_story_db_id, useful_article_ids, relation_type, used_article_relation_types)
