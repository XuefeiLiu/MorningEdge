"""Shared test fixtures."""
import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("DB_API_KEY", "test-api-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")


@pytest.fixture
def mock_supabase():
    """Return a mock Supabase client and patch get_supabase_client."""
    mock_client = MagicMock()
    with patch("backend.storage.supabase_client.get_supabase_client", return_value=mock_client):
        yield mock_client
