"""
Decide whether an overnight story deserves a long-form narrative (long_story).
Single LLM call: input title, summary, topics → JSON {"deserves_long_story": true|false}.
Criterion aligned with storyline_manager: strategy shifts, product/industry evolution,
multi-month narrative potential vs one-off or short-term only.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DESERVES_LONG_STORY_PROMPT = """You are a financial news analyst. Given a story's title, summary, and topics, decide whether it deserves a long-form narrative.

Criteria for deserves_long_story = true:
- Strategy shifts, product/industry evolution, multi-month narrative potential
- Story that will have ongoing coverage and evolving context over time

Criteria for deserves_long_story = false:
- One-off news (single event, earnings beat/miss)
- Short-term only (e.g. next-day reaction, single headline)

Story:
Title: {title}
Summary: {summary}
Topics: {topics}

Return a single JSON object with exactly one key: "deserves_long_story" (boolean).
Example: {{"deserves_long_story": true}}
Return only the JSON object, nothing else."""


async def deserves_long_story(
    llm_client: AsyncOpenAI,
    model: str,
    title: str,
    summary: str,
    topics: Optional[List[str]] = None,
) -> bool:
    """
    Call LLM to decide if this story deserves a long-form narrative.
    Returns True if the story deserves a long story, False otherwise.
    On parse/API errors, returns False (skip long-story flow).
    """
    title = (title or "").strip()
    summary = (summary or "").strip()
    topics_str = ", ".join(topics) if isinstance(topics, list) and topics else (str(topics) if topics else "")
    prompt = DESERVES_LONG_STORY_PROMPT.format(
        title=title or "(no title)",
        summary=summary or "(no summary)",
        topics=topics_str or "(none)",
    )
    try:
        resp = await llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = (resp.choices or [{}])[0].message.content if resp.choices else ""
        if not content:
            logger.debug("Deserves-long-story LLM returned empty content")
            return False
        content = content.strip()
        # Strip markdown code block if present
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```\s*$", "", content)
        obj = json.loads(content)
        return bool(obj.get("deserves_long_story", False))
    except json.JSONDecodeError as e:
        logger.warning("Deserves-long-story LLM response not valid JSON: %s", e)
        return False
    except Exception as e:
        logger.warning("Deserves-long-story LLM call failed: %s", e)
        return False
