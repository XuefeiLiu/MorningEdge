"""Watchlist CRUD endpoints."""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from backend.models import WatchlistUpdateRequest, WatchlistResponse
from backend.storage.watchlist_manager import watchlist_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/watchlist", response_model=WatchlistResponse, tags=["Watchlist"])
async def get_watchlist():
    """Get the current watchlist of stock symbols."""
    symbols = watchlist_manager.get_symbols()
    updated_at = watchlist_manager.get_updated_at() or datetime.utcnow()
    return WatchlistResponse(symbols=symbols, updated_at=updated_at)


@router.put("/watchlist", response_model=WatchlistResponse, tags=["Watchlist"])
async def update_watchlist(request: WatchlistUpdateRequest):
    """Update the watchlist with a new set of symbols. Replaces the existing watchlist."""
    if not request.symbols:
        raise HTTPException(status_code=400, detail="Symbols list cannot be empty")
    for symbol in request.symbols:
        if not symbol.strip() or len(symbol) > 10:
            raise HTTPException(status_code=400, detail=f"Invalid symbol: {symbol}")
    result = watchlist_manager.set_symbols(request.symbols)
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )


@router.post("/watchlist/add", response_model=WatchlistResponse, tags=["Watchlist"])
async def add_symbol(symbol: str = Query(..., description="Stock symbol to add")):
    """Add a single symbol to the watchlist."""
    if not symbol.strip() or len(symbol) > 10:
        raise HTTPException(status_code=400, detail=f"Invalid symbol: {symbol}")
    result = watchlist_manager.add_symbol(symbol)
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )


@router.delete("/watchlist/{symbol}", response_model=WatchlistResponse, tags=["Watchlist"])
async def remove_symbol(symbol: str):
    """Remove a symbol from the watchlist."""
    result = watchlist_manager.remove_symbol(symbol)
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )


@router.delete("/watchlist", response_model=WatchlistResponse, tags=["Watchlist"])
async def clear_watchlist():
    """Clear all symbols from the watchlist."""
    result = watchlist_manager.clear()
    return WatchlistResponse(
        symbols=result["symbols"],
        updated_at=datetime.fromisoformat(result["updated_at"])
    )
