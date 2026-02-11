"""
Overnight pipeline: story-first clustering and next-morning risk (per overnight.md).
Anchors = Gemini-sourced rows in news_articles; anchored + graph clustering; one LLM call per story.
"""
from backend.pipeline.overnight_pipeline.runner import run_overnight_pipeline  # noqa: E402

__all__ = ["run_overnight_pipeline"]
