"""
Centralized prompts for macro digest: router (§7.1), daily topic brief synthesis (§7.2), impact (§7.3).
Aligned with prompt_demo.md: per-asset system + user prompts (Tasks 1–5, constraints), per-asset JSON schemas.
Policy (Fiscal, Monetary, Trump) uses generic mechanism/transmission.
"""
from typing import List, Dict, Any

# ---- 7.2 Synthesis: per-asset SYSTEM prompts (from prompt_demo.md) ----
SYNTHESIS_SYSTEM_FX = """You are a senior FX strategist at a global macro hedge fund.
You think in relative prices, real rate differentials, balance-of-payments, and risk regimes.
Use ONLY the provided items. No source → no claim. Use current official titles (e.g. President, not Former President)."""

SYNTHESIS_SYSTEM_RATES = """You are a senior rates strategist covering the US, Europe, and Japan.
You decompose moves into policy expectations vs term premium.
Use ONLY the provided items. No source → no claim. Use current official titles (e.g. President, not Former President)."""

SYNTHESIS_SYSTEM_COMMODITY = """You are a senior commodities strategist.
You anchor on physical supply/demand, then layer macro and financial conditions.
Use ONLY the provided items. No source → no claim. Use current official titles (e.g. President, not Former President)."""

SYNTHESIS_SYSTEM_CREDIT = """You are a senior credit strategist covering IG, HY, and credit derivatives.
You think in default risk, refinancing conditions, and liquidity.
Use ONLY the provided items. No source → no claim. Use current official titles (e.g. President, not Former President)."""

SYNTHESIS_SYSTEM_EQUITY = """You are a senior macro equity strategist.
You decompose equity moves into earnings, discount rates, and risk premia.
Focus on equities in or relevant to the Nasdaq 100 (major US large-cap tech and growth names).
Use ONLY the provided items. No source → no claim. Use current official titles (e.g. President, not Former President)."""

SYNTHESIS_SYSTEM_POLICY = """You are a global macro analyst. Produce ONE daily analyst report per topic using ONLY the provided items.
Do not use external knowledge. No source → no claim.
Use current official titles: refer to the incumbent US president as "President" (e.g. President Trump), never "Former President"."""

# Fallback when topic not in map
SYNTHESIS_SYSTEM = """You are a global macro analyst. Produce ONE daily analyst report per topic using ONLY the provided items.
No source → no claim. Use current official titles (e.g. President, not Former President)."""


def get_synthesis_system(topic: str) -> str:
    """Return system prompt for the given topic (FX, RATE, CREDIT, COMMODITY, EQUITY, Fiscal Policy, Monetary Policy, Trump)."""
    m = {
        "FX": SYNTHESIS_SYSTEM_FX,
        "RATE": SYNTHESIS_SYSTEM_RATES,
        "CREDIT": SYNTHESIS_SYSTEM_CREDIT,
        "COMMODITY": SYNTHESIS_SYSTEM_COMMODITY,
        "EQUITY": SYNTHESIS_SYSTEM_EQUITY,
        "Fiscal Policy": SYNTHESIS_SYSTEM_POLICY,
        "Monetary Policy": SYNTHESIS_SYSTEM_POLICY,
        "Trump": SYNTHESIS_SYSTEM_POLICY,
    }
    return m.get(topic, SYNTHESIS_SYSTEM)


# ---- 7.2 Synthesis: per-asset USER prompts + JSON schemas (from prompt_demo.md) ----
# FX
FX_USER_TEMPLATE = """Analyze the following macro news and developments from an FX market perspective.

Topic: {topic}
Date: {date}
Items (use only these; cite sources):
{items_json}

Reference (macro book excerpts; use to frame regime, transmission, scenario where relevant):
{kb_excerpts}

Tasks:
1) Identify the dominant FX regime: risk-on/risk-off, rates-differential driven, capital flow/BoP driven, or policy credibility/political risk driven.
2) Transmission mechanisms (mandatory): For each relevant currency bloc (USD, EUR, JPY, GBP, CNY, EM FX), what changed in nominal rate expectations, real rate differentials, growth vs inflation perception, external balance or capital flows? Explain why FX should move, not just that it moved.
3) Relative-value logic: Why should Currency A outperform Currency B? Who is the marginal buyer/seller (real money, CTAs, hedgers, reserve managers)?
4) Scenario framework: Base case (1–4 weeks) expected direction for key pairs; risk/tail case; key invalidation conditions.
5) Trade relevance: Structural trend vs tactical move vs noise; trades that only work if specific macro follow-through occurs.

Constraints: No single-country FX analysis without relative justification. No generic "risk-on/risk-off" language. If impact is unclear, state FX-neutral and explain why.

Return valid JSON only:
{{
  "title": "FX-{date}",
  "summary": "Concatenated bullets or short paragraph",
  "summary_bullets": ["... [Source](url)", "..."],
  "sources": [{{ "source": "...", "url": "..." }}],
  "coverage_gap": true or false,
  "regime": "text or object (dominant regime)",
  "transmission_by_bloc": {{ "USD": "...", "EUR": "...", "JPY": "...", ... }} or array,
  "relative_value_logic": "text",
  "scenario_framework": {{ "base_case": "...", "risk_case": "...", "invalidation": "..." }} or text,
  "trade_relevance": "text"
}}"""

# Rates
RATES_USER_TEMPLATE = """Analyze the following macro news from a rates market perspective.

Topic: {topic}
Date: {date}
Items (use only these; cite sources):
{items_json}

Reference (macro book excerpts; use to frame regime, transmission, scenario where relevant):
{kb_excerpts}

Tasks:
1) Classify the macro shock: growth shock, inflation shock, policy credibility shock, fiscal/supply/issuance shock, or risk sentiment shock.
2) Central bank reaction function: How does this news alter near-term policy path, terminal rate expectations, duration of restrictive or accommodative stance?
3) Curve decomposition: Analyze impact separately on front end (0–2y), belly (2–5y), long end (10y+). For each: direction and driver (policy path, term premium, supply, hedging demand).
4) Cross-market consistency: Do FX, breakevens, and equities confirm the rates signal? If inconsistent, explain the tension.
5) Trade and risk framing: Curve steepener/flattener? Duration long/short? Rates volatility? What data or event would invalidate this view?

Constraints: No "hawkish/dovish = yields up/down" shorthand. Always separate policy expectations from term premium. Explicitly state confidence and uncertainty.

Return valid JSON only:
{{
  "title": "RATE-{date}",
  "summary": "Concatenated bullets or short paragraph",
  "summary_bullets": ["... [Source](url)", "..."],
  "sources": [{{ "source": "...", "url": "..." }}],
  "coverage_gap": true or false,
  "shock_classification": "text",
  "reaction_function": "text or object",
  "curve_decomposition": {{ "front_end": "...", "belly": "...", "long_end": "..." }} or text,
  "cross_market_consistency": "text",
  "trade_risk_framing": "text"
}}"""

# Credit
CREDIT_USER_TEMPLATE = """Analyze the following macro news from a credit market perspective.

Topic: {topic}
Date: {date}
Items (use only these; cite sources):
{items_json}

Reference (macro book excerpts; use to frame regime, transmission, scenario where relevant):
{kb_excerpts}

Tasks:
1) Macro-to-credit transmission: Impact on corporate cash flows, refinancing conditions, default probabilities; near-term vs lagged effects.
2) Spread decomposition: Assess impact on risk-free rate component, default risk premium, liquidity/risk aversion premium.
3) Segmentation: IG vs HY; cyclical vs defensive sectors; short-duration vs long-duration credit.
4) Cross-asset validation: Do equities, rates, and FX confirm the credit signal? If spreads look mispriced, explain why.
5) Portfolio implications: Credit-positive/neutral/negative (risk-adjusted); carry harvesting vs de-risking.

Constraints: No generic "risk-on/risk-off" language. Always discuss liquidity and refinancing channels. Explicitly flag macro–credit disconnects.

Return valid JSON only:
{{
  "title": "CREDIT-{date}",
  "summary": "Concatenated bullets or short paragraph",
  "summary_bullets": ["... [Source](url)", "..."],
  "sources": [{{ "source": "...", "url": "..." }}],
  "coverage_gap": true or false,
  "macro_credit_transmission": "text or object",
  "spread_decomposition": {{ "risk_free": "...", "default_premium": "...", "liquidity_premium": "..." }} or text,
  "segmentation": {{ "ig_vs_hy": "...", "cyclical_vs_defensive": "...", "duration": "..." }} or text,
  "cross_asset_validation": "text",
  "portfolio_implications": "text"
}}"""

# Commodity
COMMODITY_USER_TEMPLATE = """Analyze the following macro news from a commodities perspective.

Topic: {topic}
Date: {date}
Items (use only these; cite sources):
{items_json}

Reference (macro book excerpts; use to frame regime, transmission, scenario where relevant):
{kb_excerpts}

Tasks:
1) Physical balance assessment: Impact on supply (production, disruptions, inventories) and demand (growth, substitution, seasonality); immediate vs lagged effects.
2) Macro overlay: Growth-sensitive vs inflation-driven vs geopolitical; interaction with USD and real rates.
3) Segmentation: Analyze separately energy, industrial metals, precious metals, agriculture.
4) Price vs fundamentals: If price moved, is it justified by fundamentals or positioning? If not yet priced, what catalyst forces repricing?
5) Scenario and risk: Base case outlook (weeks to months); tail risks (geopolitics, policy intervention, weather); asymmetric opportunities.

Constraints: No "commodities = inflation hedge" clichés. Explicitly state macro vs micro-driven trades. If impact is second-order, say so.

Return valid JSON only:
{{
  "title": "COMMODITY-{date}",
  "summary": "Concatenated bullets or short paragraph",
  "summary_bullets": ["... [Source](url)", "..."],
  "sources": [{{ "source": "...", "url": "..." }}],
  "coverage_gap": true or false,
  "physical_balance": "text or object",
  "macro_overlay": "text",
  "segmentation": {{ "energy": "...", "industrial_metals": "...", "precious_metals": "...", "agriculture": "..." }} or text,
  "price_vs_fundamentals": "text",
  "scenario_risk": "text or object"
}}"""

# Equity (Nasdaq 100 focus)
EQUITY_USER_TEMPLATE = """Analyze the following macro news from an equity market perspective. Focus on equities in or relevant to the Nasdaq 100 (major US large-cap tech and growth names).

Topic: {topic}
Date: {date}
Items (use only these; cite sources):
{items_json}

Reference (macro book excerpts; use to frame regime, transmission, scenario where relevant):
{kb_excerpts}

Tasks:
1) Equity impact decomposition: Earnings level vs growth vs margins; discount rate effects (real rates); equity risk premium/volatility effects.
2) Index vs factor impact: Index-level vs factor-level; growth vs value; cyclicals vs defensives; small vs large cap. Prefer Nasdaq 100 context where applicable.
3) Macro consistency check: Are rates and FX supportive or contradictory? If equities diverge from macro signals, explain why.
4) Positioning and flows: Fundamentals vs positioning vs systematic flows; sustainability of the move.
5) Actionable framing: Regime shift vs tactical rally vs noise; data or events that would confirm or break the narrative.

Constraints: No "stocks up because optimism" explanations. Always separate earnings effects from rate effects. Highlight unresolved macro–equity tensions.

Return valid JSON only:
{{
  "title": "EQUITY-{date}",
  "summary": "Concatenated bullets or short paragraph",
  "summary_bullets": ["... [Source](url)", "..."],
  "sources": [{{ "source": "...", "url": "..." }}],
  "coverage_gap": true or false,
  "impact_decomposition": "text or object",
  "index_vs_factor": {{ "index_level": "...", "growth_vs_value": "...", "cyclicals_vs_defensives": "..." }} or text,
  "macro_consistency": "text",
  "positioning_flows": "text",
  "actionable_framing": "text"
}}"""

# Policy (Fiscal Policy, Monetary Policy, Trump)
POLICY_USER_TEMPLATE = """Topic: {topic}
Date: {date}
Items (use only these; cite sources):
{items_json}

Reference (macro book excerpts; use to frame regime, transmission, scenario where relevant):
{kb_excerpts}

Write ONE daily analyst report with strict grounding:
- Title (e.g. "{topic}-{date}")
- Summary bullets (6–12). EACH bullet ends with citations like [Source](url)
- What changed today vs yesterday (2–4 bullets) — only if supported by items
- Why it matters (2–4 bullets) — tied to cited items
- Mechanism: How does this news drive a change in a macro variable?
- Transmission: How does that variable change transmit to other variables and markets?
- Coverage note: If <3 strong items, set coverage_gap=true and include "No major confirmed developments…"
- sources: list of {{ "source": "...", "url": "..." }}

Return valid JSON only:
{{
  "title": "...",
  "summary": "Concatenated bullets or short paragraph",
  "summary_bullets": ["... [Source](url)", "..."],
  "sources": [{{ "source": "...", "url": "..." }}],
  "coverage_gap": true or false,
  "mechanism": "text",
  "transmission": "text"
}}"""


SYNTHESIS_USER_TEMPLATES: Dict[str, str] = {
    "FX": FX_USER_TEMPLATE,
    "RATE": RATES_USER_TEMPLATE,
    "CREDIT": CREDIT_USER_TEMPLATE,
    "COMMODITY": COMMODITY_USER_TEMPLATE,
    "EQUITY": EQUITY_USER_TEMPLATE,
    "Fiscal Policy": POLICY_USER_TEMPLATE,
    "Monetary Policy": POLICY_USER_TEMPLATE,
    "Trump": POLICY_USER_TEMPLATE,
}


def build_synthesis_user(
    topic: str,
    date_str: str,
    items: List[Dict[str, Any]],
    kb_excerpts: str = "",
) -> str:
    """Build user message for synthesis: topic, date, items, and optional macro book excerpts. Uses per-topic prompt from prompt_demo."""
    import json
    items_json = json.dumps(items, default=str)
    if not kb_excerpts or not kb_excerpts.strip():
        kb_excerpts = "No reference excerpts for this run."
    template = SYNTHESIS_USER_TEMPLATES.get(topic)
    if not template:
        template = POLICY_USER_TEMPLATE
    return template.format(
        topic=topic,
        date=date_str,
        items_json=items_json,
        kb_excerpts=kb_excerpts,
    )


# ---- 7.3 Impact (used in impact.py) ----
IMPACT_SYSTEM = """You are a global macro strategist. Use provided knowledge excerpts to reason about transmission mechanisms and market impact. If excerpts are insufficient, state limits explicitly.
Use current official titles for officeholders: refer to the incumbent US president as "President" (e.g. President Trump), never "Former President"."""

IMPACT_USER_TEMPLATE = """As-of date: {date}
Portfolio (optional): {portfolio}

Daily macro topic briefs (with mechanism, transmission, relative_value):
{briefs_json}

Retrieved knowledge excerpts:
{excerpts}

Task:
1) Map news/variables to factors (rates, FX, credit, growth, risk_sentiment).
2) For each topic, explain transmission channels to FX, Rates, Equity, Commodities.
3) Provide base case and risk case: expected direction (↑/↓/↔) for key assets, signposts, confidence 0–100.
4) Portfolio impact: winners/losers, 3 concrete actions (hedge/trim/add/wait) with rationale.
5) Include relative-value implications (curve 2y/10y, cross-currency basis, CDS, swap–Treasury) where relevant.

Return valid JSON:
{{
  "report_markdown": "narrative summary (markdown)",
  "factor_mapping": {{ "news/variable": "factor", ... }},
  "factor_impacts": [{{ "factor": "...", "move": "...", "portfolio_effect": "..." }}],
  "signals": [{{ "action": "...", "reason": "...", "confidence": 0-100 }}],
  "topics": ["FX", "RATE", ...]
}}"""


def build_impact_user(
    date_str: str,
    briefs_json: str,
    excerpts: str,
    portfolio: str = "{}",
) -> str:
    return IMPACT_USER_TEMPLATE.format(
        date=date_str,
        portfolio=portfolio,
        briefs_json=briefs_json,
        excerpts=excerpts,
    )


# ---- Daily summary of summaries (FX, RATE, ... → one daily macro summary) ----
DAILY_SUMMARY_SYSTEM = """You are a senior global macro strategist. Given the 8 topic briefs (FX, Rates, Credit, Commodity, Equity, Fiscal Policy, Monetary Policy, Trump) for a single day, produce ONE concise daily macro summary that:
1) Highlights the 2–4 most important cross-asset themes and policy developments.
2) Preserves key takeaways from each topic without repeating verbatim.
3) Is written for a portfolio manager: actionable, short (2–4 paragraphs or equivalent bullets).
4) Uses clear, professional language. No hedging phrases like "it remains to be seen" unless uncertainty is material."""

DAILY_SUMMARY_USER_TEMPLATE = """Date: {date}

Topic briefs (topic, title, summary):

{briefs_text}

Produce a single daily macro summary. Return valid JSON only:
{{
  "title": "Short headline for the day (e.g. 'Rates repricing, FX risk-off')",
  "summary": "2–4 paragraph narrative or one concise paragraph.",
  "summary_bullets": ["Bullet one.", "Bullet two.", "…"]
}}"""


def build_daily_summary_user(date_str: str, briefs: List[Dict[str, Any]]) -> str:
    """Format topic briefs (each with topic, title, summary) into text for the LLM."""
    lines = []
    for b in briefs:
        topic = b.get("topic") or "Topic"
        title = (b.get("title") or "").strip()
        summary = (b.get("summary") or "").strip()
        lines.append(f"=== {topic} ===\nTitle: {title}\nSummary: {summary}")
    briefs_text = "\n\n".join(lines) if lines else "(No topic briefs provided.)"
    return DAILY_SUMMARY_USER_TEMPLATE.format(date=date_str, briefs_text=briefs_text)
