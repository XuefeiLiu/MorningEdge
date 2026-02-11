"""
Watchlist storage and management.
"""
import json
import os
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from backend.config import WATCHLIST_FILE


class WatchlistManager:
    """Manages the persisted watchlist of stock symbols."""
    
    def __init__(self, file_path: Optional[str] = None):
        self.file_path = Path(file_path or WATCHLIST_FILE)
        self._ensure_file_exists()
    
    def _ensure_file_exists(self) -> None:
        """Ensure the watchlist file exists with default structure. Default demo symbols: NFLX, AAPL."""
        if not self.file_path.exists():
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self._save_data({
                "symbols": ["AAPL", "NFLX"],
                "updated_at": datetime.utcnow().isoformat()
            })
    
    def _load_data(self) -> dict:
        """Load watchlist data from file."""
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"symbols": [], "updated_at": None}
    
    def _save_data(self, data: dict) -> None:
        """Save watchlist data to file."""
        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=4, default=str)
    
    def get_symbols(self) -> List[str]:
        """Get the current list of watched symbols."""
        data = self._load_data()
        return data.get("symbols", [])
    
    def get_updated_at(self) -> Optional[datetime]:
        """Get the last update timestamp."""
        data = self._load_data()
        updated_at = data.get("updated_at")
        if updated_at:
            return datetime.fromisoformat(updated_at)
        return None
    
    def set_symbols(self, symbols: List[str]) -> dict:
        """Set the watchlist symbols (replaces existing)."""
        # Normalize symbols to uppercase and remove duplicates
        normalized = list(set(s.upper().strip() for s in symbols if s.strip()))
        data = {
            "symbols": sorted(normalized),
            "updated_at": datetime.utcnow().isoformat()
        }
        self._save_data(data)
        return data
    
    def add_symbol(self, symbol: str) -> dict:
        """Add a single symbol to the watchlist."""
        symbols = self.get_symbols()
        normalized = symbol.upper().strip()
        if normalized and normalized not in symbols:
            symbols.append(normalized)
        return self.set_symbols(symbols)
    
    def remove_symbol(self, symbol: str) -> dict:
        """Remove a single symbol from the watchlist."""
        symbols = self.get_symbols()
        normalized = symbol.upper().strip()
        if normalized in symbols:
            symbols.remove(normalized)
        return self.set_symbols(symbols)
    
    def clear(self) -> dict:
        """Clear all symbols from the watchlist."""
        return self.set_symbols([])


# Global instance
watchlist_manager = WatchlistManager()
