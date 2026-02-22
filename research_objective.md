# MorningEdge – Research Objective Framework

## 1. Core Research Thesis

Markets are increasingly driven by narrative shifts rather than isolated data points.

MorningEdge aims to:

- Detect macro & equity narrative transitions
- Quantify tone shifts in structured form
- Translate narrative regimes into tradable signals
- Predict short-horizon risk (e.g., overnight risk)

This is not a news aggregator.
This is a narrative regime detection engine.

---

## 2. Primary Research Questions

### Q1: Narrative Shift Detection
Can embedding-based similarity and clustering detect macro regime transitions earlier than market repricing?

### Q2: Tone Diffusion
Does the diffusion of hawkish/dovish language across multiple articles predict front-end rate repricing?

### Q3: Storyline Persistence
Do persistent storylines generate measurable cross-asset impact?

### Q4: Narrative Surprise
When narrative tone deviates from priced expectations, does it create alpha?

---

## 3. Signal Construction Philosophy

Signals must be:

- Decomposable
- Explainable
- Reproducible
- Backtestable

Avoid:

- Opaque LLM-only scoring
- Non-deterministic outputs
- Signals without attribution

Signal template:

    Final Signal =
        w1 * Sentiment Component
      + w2 * Narrative Shift Component
      + w3 * Diffusion Component
      + w4 * Market Alignment Component

Weights must be configurable.

---

## 4. Core Signal Modules

### 4.1 Sentiment Component
- Hawkish vs dovish tone similarity
- Inflation concern score
- Growth risk score

### 4.2 Narrative Shift Component
- Embedding centroid drift
- Rolling cosine distance
- PCA regime change detection

### 4.3 Diffusion Component
- % of articles in hawkish cluster
- Cross-source tone dispersion
- Storyline expansion velocity

### 4.4 Market Alignment Component
- Compare narrative signal vs:
    - 2Y yield change
    - SOFR futures repricing
    - MOVE index
    - Equity volatility

Goal:
Identify narrative/market divergence.

---

## 5. Backtesting Framework

Evaluate signals on:

- Overnight SPX return
- 2Y Treasury yield change
- USD index move
- Sector rotation

Metrics:

- Information Ratio
- Hit Ratio
- Max Drawdown
- Turnover
- Regime stability

No signal is valid without:
- Out-of-sample test
- Stability check
- Sensitivity analysis

---

## 6. Optimization Protocol

Agents may optimize:

- Lookback windows
- Clustering parameters
- Embedding similarity thresholds
- Weight allocation

Agents must NOT:

- Overfit to in-sample performance
- Change signal definition without logging
- Remove interpretability

---

## 7. Experimental Sandbox

All experimental ideas must be placed under:

    /research/

Examples:

- Alternative embedding model
- HMM regime detection
- Bayesian tone inference
- Cross-country narrative divergence

Production signals must remain stable.

---

## 8. Long-Term Vision

MorningEdge evolves into:

- Narrative Risk Engine
- Macro Regime Classifier
- Institutional-grade signal platform
- AI-augmented macro research assistant

Ultimate objective:

Bridge unstructured narrative data
→ structured regime variables
→ tradable macro signals.

---

End of Research Objective Document.