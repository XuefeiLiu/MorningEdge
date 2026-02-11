"""Tests for API endpoints using FastAPI TestClient."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    # Patch validate_config to avoid needing real env vars at import time
    with patch("backend.config.validate_config"):
        from backend.main import app
        with TestClient(app) as c:
            yield c


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        assert "timestamp" in data


class TestWatchlistEndpoint:
    def test_get_watchlist(self, client):
        with patch("backend.routers.watchlist.watchlist_manager") as mock_wm:
            mock_wm.get_symbols.return_value = ["AAPL", "MSFT"]
            mock_wm.get_updated_at.return_value = None
            response = client.get("/watchlist")
            assert response.status_code == 200
            data = response.json()
            assert data["symbols"] == ["AAPL", "MSFT"]

    def test_update_watchlist_empty_fails(self, client):
        response = client.put("/watchlist", json={"symbols": []})
        assert response.status_code == 400

    def test_update_watchlist_invalid_symbol(self, client):
        response = client.put("/watchlist", json={"symbols": ["TOOLONGSYMBOL1"]})
        assert response.status_code == 400
