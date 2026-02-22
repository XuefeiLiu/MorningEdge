# ETF Support Integration Plan

## Context

MorningEdge currently only supports individual stocks (NASDAQ 100). The entire pipeline — news collection, embedding, clustering, story generation, briefing — is ticker-based with no asset type distinction. The user wants to add ETF support with: a predefined ETF list, an independent "ETF" tab in the frontend, SEC filing logic skipped for ETFs, and ETF-specific analysis (component stock changes, adjusted signal weights).

The architecture is already 95% ETF-ready since everything flows through generic ticker fields. The main work is: schema tagging, ETF data list, conditional SEC filing skip, LLM prompt adjustment, and frontend tab addition.

---

## Phase 1: Database + Backend Data Layer

### 1.1 SQL migration — add `asset_type` column to `stocks` table
Run in Supabase SQL editor (create `backend/scripts/migrate_add_asset_type.sql`):
```sql
ALTER TABLE stocks ADD COLUMN asset_type TEXT NOT NULL DEFAULT 'stock';
ALTER TABLE stocks ADD CONSTRAINT chk_asset_type CHECK (asset_type IN ('stock', 'etf'));
CREATE INDEX idx_stocks_asset_type ON stocks(asset_type);
```

### 1.2 Create `backend/storage/etf_tickers.py` (new file)
Follow the same pattern as `backend/storage/nasdaq100_tickers.py`:
- `ETF_LIST_FALLBACK` — ~30 popular ETFs: SPY, QQQ, IWM, DIA, VOO, VTI, XLF, XLK, XLE, XLV, XLI, XLP, XLY, XLU, XLB, XLRE, XLC, GLD, SLV, TLT, HYG, LQD, EEM, EFA, VWO, ARKK, SOXX, SMH, KWEB, USO
- Each entry: `{"ticker": ..., "name": ..., "exchange": ...}`
- `get_etf_list(use_api=False)` function with deduplication

### 1.3 Update `backend/models.py` (line 350-354)
Add `asset_type` field to `StockInfo`:
```python
class StockInfo(BaseModel):
    ticker: str
    name: str
    exchange: str
    asset_type: str = "stock"  # "stock" or "etf"
```

### 1.4 Update `backend/storage/stocks_save.py` (line 39-46)
Include `asset_type` in upsert payload:
```python
"asset_type": stock.get("asset_type", "stock"),
```

### 1.5 Update `backend/storage/stocks_query.py`
Add `get_stocks_by_type(supabase, asset_type)` function that filters by `asset_type`.

### 1.6 Update `backend/storage/stocks_main.py`
After NASDAQ 100 population, also populate ETFs:
- Import `get_etf_list` from `etf_tickers.py`
- Tag each ETF entry with `"asset_type": "etf"`
- Call `save_stocks(supabase, etf_data)`

---

## Phase 2: API Endpoints

### 2.1 Add `/stocks/etfs` endpoint in `backend/routers/stocks.py`
New GET endpoint returning `List[StockInfo]` with `asset_type="etf"`. Follow the pattern of `/stocks/nasdaq100` (line 17-26).

### 2.2 Update `/stocks/prices` name_map in `backend/routers/stocks.py` (line 37-38)
Currently only builds name_map from NASDAQ 100. Add ETF names:
```python
from backend.storage.etf_tickers import get_etf_list
etf_stocks = get_etf_list(use_api=False)
name_map.update({e["ticker"]: e["name"] for e in etf_stocks})
```

---

## Phase 3: Pipeline — Skip SEC Filings for ETFs

### 3.1 Add ETF ticker cache helper in `backend/pipeline/overnight_pipeline/runner.py`
Add a module-level helper `_get_etf_tickers(supabase)` that returns a `set` of ETF ticker strings (cached per run). Uses `get_stocks_by_type(supabase, "etf")`.

### 3.2 Skip filing link in `runner.py` (line 290)
Before the `if story_payload.get("is_filing_related") and ticker:` block, check if ticker is ETF and skip:
```python
is_etf = ticker and ticker.upper() in etf_tickers_set
if story_payload.get("is_filing_related") and ticker and not is_etf:
    # ... existing filing link logic ...
```

### 3.3 Adjust LLM prompt for ETFs in `backend/pipeline/overnight_pipeline/story_llm.py`
In `_build_cluster_prompt()` (line 51-65):
- Add optional `is_etf: bool = False` parameter
- When `is_etf`, use ETF-specific prompt text: focus on sector/market drivers, fund flow, component stock movements; set `is_filing_related` to false
- Pass `is_etf` through `story_llm_call()` signature

### 3.4 Pass `is_etf` flag in `runner.py` LLM call (line 230-241)
Determine `is_etf` from the cluster's ticker, pass to `story_llm_call()`.

### 3.5 ETF news collection strategy (Alpha Vantage + Massive + Gemini)

Current collectors are symbol-based and can already query ETF tickers (`symbols=[ticker]`), so the integration risk is not API shape, but **coverage depth**:
- Alpha Vantage `NEWS_SENTIMENT` supports `tickers` parameter; ETF tickers can be passed the same way as equities.
- Massive `/v2/reference/news` supports `ticker` query filter; ETF tickers can be passed directly.
- Gemini is fully prompt-driven and needs ETF-specific instructions to avoid stock-earnings bias.

Implementation steps:
1. Add ETF-aware prompt routing in `backend/services/collectors/gemini.py`
2. Add `get_etf_news_prompt(symbol)` in `backend/services/collectors/prompts.py`
3. ETF prompt should prioritize:
   - fund flows (inflow/outflow, creations/redemptions)
   - index/benchmark changes and rebalances
   - underlying holdings impact (top holdings and sector concentration)
   - macro/rates/commodity drivers based on ETF exposure
4. Keep output contract unchanged (JSON array with `title/summary/url/source/published_at`) so no downstream schema change is required
5. Fallback rule for sparse direct ETF news:
   - allow one synthesized “drivers” topic using trusted sources about top holdings/index components, explicitly tied back to ETF impact
   - cap to max 5 topics to keep clustering stable

Validation checklist for ETF news:
- `collect_todays_news("SPY")` returns non-empty results from at least one source
- `collect_todays_news("QQQ")` Gemini items include ETF-style topics (flows/holdings/index/rates), not only stock earnings language
- dedup/filter pipeline still accepts items without schema changes

---

## Phase 4: Briefing Service — ETF Signal Weights

### 4.1 Add `ETF_SIGNAL_WEIGHTS` in `backend/config.py`
```python
ETF_SIGNAL_WEIGHTS = {
    "news_sentiment": 0.20,
    "technical": 0.35,
    "market_sentiment": 0.20,
    "sec_filings": 0.0,
    "macro": 0.25,
}
```

### 4.2 Update `TradingDirectionAnalyzer` in `backend/services/briefing.py`
- Add `is_etf` parameter to `analyze()` method
- Select weight dict based on `is_etf`
- Skip SEC filing signal collection for ETF symbols in `_collect_real_data()` (line 667-668)

---

## Phase 5: Frontend — ETF Tab

### 5.1 Update `frontend/types.ts` (line 12)
```typescript
export type ViewType = 'Portfolio' | 'Watchlist' | 'ETF';
```

### 5.2 Update `frontend/components/Dashboard.tsx`
**State additions** (after line 141):
- `etfList` state with `INITIAL_ETF_LIST` (SPY, QQQ, IWM, DIA, XLK, GLD, TLT)
- `etfStocksInfo` state for ETF search data
- `etfListRef` for price polling

**Data fetching**:
- Fetch `/stocks/etfs` on mount (alongside NASDAQ 100 fetch)
- Include `etfList` in price polling interval
- Save ETF list to sessionStorage

**UI changes**:
- Update `activeList` derivation (line 183) to include `currentView === 'ETF'` case
- Add "My ETFs" button in dropdown (line 570-585)
- Update dropdown title display for ETF view (line 566)
- Pass `etfStocksInfo` and `currentView` to `SearchBar`
- Update `addStockByData` and `handleRemoveStock` to handle ETF view

### 5.3 Update `frontend/components/SearchBar.tsx`
- Add `etfStocks` and `currentView` props to `SearchBarProps`
- Switch search list based on `currentView`: ETF list when `'ETF'`, NASDAQ 100 otherwise
- Update error message in `handleManualAdd()` to be context-aware
- Update placeholder text based on view

### 5.4 Update i18n files
**`frontend/i18n/locales/en.ts`** (narrative section, line 73-84):
- Add: `myETFs`, `addETF`, `addETFPlaceholder`, `noETFsInList`

**`frontend/i18n/locales/zh.ts`** (narrative section):
- Add corresponding Chinese translations

---

## Implementation Order (respecting dependencies)

1. SQL migration (1.1)
2. Backend data layer (1.2 → 1.3 → 1.4 → 1.5 → 1.6)
3. API endpoints (2.1, 2.2)
4. Pipeline SEC skip + ETF news prompting (3.1 → 3.2 → 3.3 → 3.4 → 3.5)
5. Briefing signal weights (4.1, 4.2)
6. Frontend (5.1 → 5.2 → 5.3 → 5.4)
7. Run `python backend/storage/stocks_main.py` to populate ETFs

---

## Verification

1. **DB**: Run migration SQL, then `python backend/storage/stocks_main.py` — verify ETFs appear in `stocks` table with `asset_type='etf'`
2. **API**: `curl http://localhost:8000/stocks/etfs` — should return ETF list with `asset_type: "etf"`
3. **Prices**: `curl "http://localhost:8000/stocks/prices?symbols=SPY,QQQ"` — should return prices with correct names
4. **Pipeline**: Run `python -m backend.pipeline.overnight_pipeline.runner --asof-date <date>` — verify ETF stories are generated without filing links
5. **Frontend**: `npm run dev` — verify ETF tab appears, ETFs can be added/removed, prices update, StockDetail works for ETF tickers
