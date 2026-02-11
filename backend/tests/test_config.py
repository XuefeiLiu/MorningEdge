"""Tests for config validation."""
import os
import pytest
from unittest.mock import patch


class TestValidateConfig:
    def test_valid_config(self, monkeypatch):
        """With all required keys set, validate_config should not raise."""
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("DB_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        from backend.config import validate_config
        validate_config()  # Should not raise

    def test_missing_supabase_url(self, monkeypatch, caplog):
        """Missing SUPABASE_URL should warn (default URL fallback), not raise."""
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.setenv("DB_API_KEY", "test-key")
        import logging
        with caplog.at_level(logging.WARNING):
            from backend.config import validate_config
            validate_config()
        assert "SUPABASE_URL not set" in caplog.text

    def test_missing_db_key(self, monkeypatch):
        """Missing both DB_API_KEY and SUPABASE_KEY should raise RuntimeError."""
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.delenv("DB_API_KEY", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        from backend.config import validate_config
        with pytest.raises(RuntimeError, match="DB_API_KEY"):
            validate_config()

    def test_supabase_key_fallback(self, monkeypatch):
        """SUPABASE_KEY should work as fallback for DB_API_KEY."""
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.delenv("DB_API_KEY", raising=False)
        monkeypatch.setenv("SUPABASE_KEY", "fallback-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
        from backend.config import validate_config
        validate_config()  # Should not raise

    def test_missing_openai_warns(self, monkeypatch, caplog):
        """Missing OPENAI_API_KEY should log a warning, not raise."""
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("DB_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # Also patch the module-level variable (loaded at import time)
        import backend.config
        monkeypatch.setattr(backend.config, "OPENAI_API_KEY", None)
        import logging
        with caplog.at_level(logging.WARNING):
            from backend.config import validate_config
            validate_config()
        assert "OPENAI_API_KEY" in caplog.text
