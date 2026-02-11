"""
Overnight pipeline configuration: clustering thresholds, filing buffer, LLM settings.
"""
import os

# Clustering (overnight.md Section 7). Lower thresholds = fewer, larger clusters (more articles per cluster).
T_ASSIGN = float(os.getenv("OVERNIGHT_T_ASSIGN", "0.68"))  # attach article to anchor if score >= this (lower = more assigned to anchors)
T_GRAPH = float(os.getenv("OVERNIGHT_T_GRAPH", "0.62"))   # edge between unmatched articles if cos_sim >= this (lower = fewer discovered clusters)

# Filing linkage: most recent = row with latest sec_filings.filed_date (no hour buffer)

# LLM
OVERNIGHT_LLM_MODEL = os.getenv("OVERNIGHT_LLM_MODEL", "gpt-4o-mini")
PROMPT_VERSION = os.getenv("OVERNIGHT_PROMPT_VERSION", "v1")

# Optional chunk evidence: top-k chunks from linked filing
FILING_CHUNK_TOP_K = int(os.getenv("OVERNIGHT_FILING_CHUNK_TOP_K", "5"))
