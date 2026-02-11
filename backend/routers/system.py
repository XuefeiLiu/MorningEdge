"""System endpoints: health check and configuration status."""
import logging
from datetime import datetime

from fastapi import APIRouter

from backend.models import HealthResponse, ConfigResponse
from backend.storage.watchlist_manager import watchlist_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check system health and status."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="1.0.0"
    )


@router.get("/config", response_model=ConfigResponse, tags=["System"])
async def get_config():
    """Get current system configuration status."""
    from backend.config import ALPHA_VANTAGE_API_KEY, OPENAI_API_KEY

    data_sources = ["SEC EDGAR (free)", "FRED (free)", "Nasdaq RSS (free)"]
    if ALPHA_VANTAGE_API_KEY:
        data_sources.append("Alpha Vantage (configured)")
    else:
        data_sources.append("Alpha Vantage (mock fallback)")

    return ConfigResponse(
        alpha_vantage_configured=bool(ALPHA_VANTAGE_API_KEY),
        openai_configured=bool(OPENAI_API_KEY),
        watchlist_count=len(watchlist_manager.get_symbols()),
        data_sources=data_sources
    )
