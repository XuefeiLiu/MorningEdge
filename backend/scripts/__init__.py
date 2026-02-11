"""
Maintenance scripts: backfill and remove duplicates.

- backfill_long_storylines: Backfill long storylines for short storylines missing long_storyline_id.
- backfill_embeddings: Backfill embeddings for news_articles without embeddings.
- backfill_embeddings_new_model: Re-embed all rows (news_articles, macro_articles, sec_filing_chunks) with OpenAI text-embedding-3-small (1536-dim). Run DB migration first.
- remove_long_storylines: Remove all long storylines and their links.
- remove_duplicate_storylines: Remove duplicate short and long storylines (by title per ticker).
- cleanup_orphan_storylines: Delete long_stories that have no linked articles in long_story_article_links.
- remove_duplicate_news_articles: Remove duplicate news_articles (same title on same day per ticker).
"""
