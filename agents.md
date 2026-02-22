# MorningEdge – Agent Operating Guide

## 1. Project Overview

MorningEdge is an AI-powered macro & equity narrative intelligence system.

Core objective:
- Aggregate multi-source financial news and macro data
- Cluster into structured storylines
- Generate macro digests
- Produce narrative-based risk signals (e.g., overnight risk)

This repository contains:
- Backend (FastAPI)
- Data ingestion pipelines
- Embedding & clustering logic
- Supabase/PostgreSQL integration
- Narrative / RAG modules

---

## 2. Architectural Principles

Agents must follow these design principles:

1. Modularity
   - Do not introduce monolithic files.
   - Keep ingestion, embedding, clustering, signal logic separated.

2. Deterministic Pipelines
   - No hidden randomness without seed control.
   - Signals must be reproducible.

3. Database Integrity
   - Never modify schema without explicit migration logic.
   - All schema changes must be backward compatible.

4. Production-Oriented
   - Avoid notebook-style inline experiments.
   - Prefer pipeline modules over ad-hoc scripts.

---

## 3. Core Data Tables (Conceptual)

### news_articles
- id
- title
- content
- source
- published_at
- embedding (vector)
- relevance_score

### macro_articles
- Similar structure to news_articles

### storylines
- id
- narrative_summary
- cluster_id
- topic_label
- confidence_score

### storyline_links
- article_id
- storyline_id
- relationship_type

Agents must NOT:
- Drop existing columns
- Change embedding dimension without global update
- Rename core tables

---

## 4. Embedding Rules

- All embeddings must use consistent dimension.
- Any model change must:
  - Update embedding dimension everywhere
  - Provide migration plan
  - Recompute embeddings safely

Do not mix embedding dimensions in the same table.

---

## 5. Signal Generation Constraints

Narrative signals must:

- Be explainable
- Be decomposable into components
- Be backtestable
- Avoid black-box scoring without attribution

Signals should be structured like:

    final_score =
        w1 * sentiment_component
      + w2 * narrative_shift_component
      + w3 * macro_alignment_component

Weights must be configurable.

---

## 6. Clustering Guidelines

When modifying clustering:

- Justify choice (KMeans / HDBSCAN / etc.)
- Evaluate cluster coherence
- Avoid arbitrary cluster counts
- Preserve storyline_id consistency

---

## 7. RAG & Narrative Reasoning

RAG must:

- Be retrieval-first (not hallucination-first)
- Return citations or article references
- Never fabricate narrative sources

Agent should prioritize:
1. Relevant article retrieval
2. Structured summarization
3. Risk interpretation

---

## 8. Performance Constraints

- Avoid O(n²) operations on full article history
- Use batching for embeddings
- Respect API rate limits
- Do not introduce blocking synchronous calls in critical paths

---

## 9. Deployment Awareness

Current deployment assumptions:

- Backend: FastAPI
- DB: Supabase (PostgreSQL + pgvector)
- Hosting: Railway / Vercel
- Environment variables required

Agents must:
- Never hardcode secrets
- Use environment variables
- Maintain .env template consistency

---

## 10. Optimization Objective

MorningEdge optimizes for:

1. Narrative clarity
2. Signal robustness
3. Macro relevance
4. System scalability
5. Quant-research credibility

Not optimizing for:
- UI aesthetics
- Social media virality
- Pure LLM creativity without structure

---

## 11. What Agents May Modify

Agents MAY:

- Improve embedding logic
- Improve clustering
- Improve scoring formula
- Add modular signal components
- Add testing scripts
- Improve performance

Agents MUST NOT:

- Remove production endpoints
- Break API contracts
- Change DB schema without migration
- Introduce experimental hacks in production paths

---

## 12. Research Mode vs Production Mode

If adding experimental features:

- Place under /research
- Do not modify production pipeline
- Clearly label experimental modules

---

## 13. Long-Term Vision

MorningEdge aims to evolve into:

- Structured narrative intelligence engine
- Regime detection system
- Macro signal generator
- Institutional-grade research platform

All improvements should align with this direction.

---

End of Agent Operating Guide.