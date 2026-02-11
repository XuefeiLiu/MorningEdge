"""
Rate limit and daily quota for Ask (POST /storylines/custom) to limit token usage.
In-memory store keyed by client IP; optional daily quota per IP.
"""
import asyncio
import logging
import time
from collections import deque
from typing import Optional, Tuple

from backend.config import (
    ASK_RATE_LIMIT_PER_MINUTE,
    ASK_RATE_LIMIT_WINDOW_SECONDS,
    ASK_DAILY_QUOTA_PER_IP,
)

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
# Sliding window: ip -> deque of request timestamps (within window)
_rate_timestamps: dict[str, deque[float]] = {}
# Daily quota: key "ip:YYYY-MM-DD" -> count
_daily_counts: dict[str, int] = {}
# TTL for daily keys: prune keys older than 2 days on check
_DAILY_KEY_TTL_DAYS = 2


def _utc_date_str() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _prune_old_daily_keys() -> None:
    """Remove daily keys older than _DAILY_KEY_TTL_DAYS."""
    if not _daily_counts:
        return
    cutoff = time.time() - (_DAILY_KEY_TTL_DAYS * 86400)
    # Keys are "ip:YYYY-MM-DD"; we don't store timestamp. Prune by date string.
    today = _utc_date_str()
    to_remove = [k for k in _daily_counts if k.split(":")[-1] < today and len(_daily_counts) > 1000]
    for k in to_remove[:500]:
        _daily_counts.pop(k, None)


async def check_ask_limits(client_ip: str) -> Optional[Tuple[int, str]]:
    """
    Check rate limit and daily quota for client_ip.
    Returns None if allowed, or (retry_after_seconds, detail_message) if limited.
    """
    async with _lock:
        now = time.time()
        window = ASK_RATE_LIMIT_WINDOW_SECONDS
        limit = ASK_RATE_LIMIT_PER_MINUTE

        # Rate limit: sliding window
        if limit > 0 and window > 0:
            q = _rate_timestamps.setdefault(client_ip, deque())
            # Drop timestamps outside window
            while q and q[0] < now - window:
                q.popleft()
            if len(q) >= limit:
                retry_after = max(1, int(window - (now - q[0])) if q else window)
                return (retry_after, f"Too many requests. Please try again in {retry_after} seconds.")

        # Daily quota
        if ASK_DAILY_QUOTA_PER_IP > 0:
            _prune_old_daily_keys()
            date_str = _utc_date_str()
            key = f"{client_ip}:{date_str}"
            count = _daily_counts.get(key, 0)
            if count >= ASK_DAILY_QUOTA_PER_IP:
                return (3600, f"Daily ask limit reached ({ASK_DAILY_QUOTA_PER_IP} questions per day). Try again tomorrow.")

    return None


async def record_ask(client_ip: str) -> None:
    """Record a successful Ask request for rate limit and daily quota."""
    async with _lock:
        now = time.time()
        if ASK_RATE_LIMIT_PER_MINUTE > 0 and ASK_RATE_LIMIT_WINDOW_SECONDS > 0:
            q = _rate_timestamps.setdefault(client_ip, deque())
            q.append(now)
        if ASK_DAILY_QUOTA_PER_IP > 0:
            date_str = _utc_date_str()
            key = f"{client_ip}:{date_str}"
            _daily_counts[key] = _daily_counts.get(key, 0) + 1
