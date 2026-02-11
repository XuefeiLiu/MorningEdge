"""Tests for backend.utils.helpers."""
from datetime import datetime, timezone

from backend.utils.helpers import (
    ensure_tz, parse_datetime_param, parse_latest_from_event_time_evidence,
    filing_display_title, looks_like_table, impact_score_to_level,
    sort_key_impact_score,
)


class TestEnsureTz:
    def test_none(self):
        assert ensure_tz(None) is None

    def test_naive_datetime(self):
        dt = datetime(2025, 1, 1, 12, 0, 0)
        result = ensure_tz(dt)
        assert result.tzinfo == timezone.utc

    def test_aware_datetime(self):
        dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = ensure_tz(dt)
        assert result == dt

    def test_iso_string(self):
        result = ensure_tz("2025-01-01T12:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_iso_string_with_offset(self):
        result = ensure_tz("2025-01-01T12:00:00+05:00")
        assert result is not None

    def test_garbage_string(self):
        assert ensure_tz("not-a-date") is None

    def test_empty_string(self):
        assert ensure_tz("") is None


class TestParseDatetimeParam:
    def test_none(self):
        assert parse_datetime_param(None) is None

    def test_empty(self):
        assert parse_datetime_param("") is None

    def test_valid_iso(self):
        result = parse_datetime_param("2025-06-15T10:30:00Z")
        assert result is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.tzinfo is not None

    def test_no_tz(self):
        result = parse_datetime_param("2025-06-15T10:30:00")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_garbage(self):
        assert parse_datetime_param("garbage") is None

    def test_non_string(self):
        assert parse_datetime_param(12345) is None


class TestParseLatestFromEventTimeEvidence:
    def test_none(self):
        assert parse_latest_from_event_time_evidence(None) is None

    def test_empty_list(self):
        assert parse_latest_from_event_time_evidence([]) is None

    def test_single_entry(self):
        result = parse_latest_from_event_time_evidence(["published_at=2025-06-15T10:30:00Z"])
        assert result is not None
        assert result.hour == 10

    def test_multiple_entries_returns_latest(self):
        result = parse_latest_from_event_time_evidence([
            "published_at=2025-06-15T10:00:00Z",
            "published_at=2025-06-15T18:00:00Z",
            "published_at=2025-06-15T12:00:00Z",
        ])
        assert result is not None
        assert result.hour == 18

    def test_bad_entries_skipped(self):
        result = parse_latest_from_event_time_evidence([
            "garbage",
            "published_at=2025-06-15T10:00:00Z",
            None,
        ])
        assert result is not None
        assert result.hour == 10

    def test_all_bad_entries(self):
        assert parse_latest_from_event_time_evidence(["garbage", "more garbage"]) is None


class TestFilingDisplayTitle:
    def test_full(self):
        assert filing_display_title("10-Q", "2024-09-30", 2024, "Q3") == "10-Q · Q3 2024"

    def test_10k_no_period(self):
        assert filing_display_title("10-K", "2024-12-31", None, None) == "10-K · 2024"

    def test_no_form_type(self):
        result = filing_display_title(None, None, None, None)
        assert result == "Filing"

    def test_form_only(self):
        assert filing_display_title("10-K", None, None, None) == "10-K"


class TestLooksLikeTable:
    def test_empty(self):
        assert looks_like_table("") is False
        assert looks_like_table("short") is False

    def test_pipe_table(self):
        text = "| A | B | C |\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |"
        assert looks_like_table(text) is True

    def test_prose(self):
        text = "This is a normal paragraph.\nIt has multiple lines but no tables."
        assert looks_like_table(text) is False

    def test_single_line(self):
        assert looks_like_table("| A | B | C |") is False


class TestImpactScoreToLevel:
    def test_none(self):
        assert impact_score_to_level(None) == "medium"

    def test_high(self):
        assert impact_score_to_level(0.8) == "high"

    def test_medium(self):
        assert impact_score_to_level(0.5) == "medium"

    def test_low(self):
        assert impact_score_to_level(0.1) == "low"

    def test_boundary_high(self):
        assert impact_score_to_level(0.7) == "high"

    def test_boundary_medium(self):
        assert impact_score_to_level(0.3) == "medium"


class TestSortKeyImpactScore:
    def test_null(self):
        assert sort_key_impact_score({}) == (True, 0.0)

    def test_with_score(self):
        result = sort_key_impact_score({"impact_score": 0.8})
        assert result == (False, -0.8)

    def test_invalid_score(self):
        assert sort_key_impact_score({"impact_score": "bad"}) == (True, 0.0)
