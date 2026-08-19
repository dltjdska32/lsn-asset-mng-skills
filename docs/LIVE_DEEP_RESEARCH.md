# Live Deep Research Integration

`LiveDeepResearchRuntime` is the fixed bridge between Phase 4 retrieval/evidence and Phase 5 equity analysis.
It exists to prevent a Codex session from doing a prose-only web analysis while merely claiming that the investment runtime ran.

For a selected equity, the runtime flow is:

`ProviderFallbackExecutor -> WebResearchAdapter fallback -> EvidenceResearchStore -> Freshness/selection -> financial normalization -> EquityFundamentalAnalyzer -> EquityValuationAnalyzer -> calculations/run.db`.

Codex may perform the external search, but it must pass structured hits through `WebResearchBundleBackend`. A hit needs source identity and a real data/publication timestamp. Current-price hits from news, snippets, analyst reports, blogs, or undated pages are rejected by the existing adapter. Financial news numbers are persisted but remain unapproved calculation inputs.

A financial hit should place its canonical metric in `metadata.metric` and preferably `metadata.canonical_metric`. Supported canonical metrics include `revenue`, `prior_revenue`, `operating_income`, `net_income`, `cash_from_operations`, `capex`, `total_debt`, `cash`, `equity`, `current_assets`, `current_liabilities`, `shares_outstanding`, `eps`, `ebitda`, `dividend_per_share`, `book_value_per_share`, `enterprise_value`, and `market_cap`.

Numeric financial hits used in calculations must also carry an explicit unit/scale and currency. Do not drop the source scale while extracting a filing fact. Examples: `unit: "JPY million", currency: "JPY"`, `unit: "KRW billion", currency: "KRW"`, `unit: "million shares"` for share counts, and `unit: "JPY/share"` for EPS/BVPS/DPS. `unit_scale`/`unit_multiplier` metadata may be used when a source uses a non-standard label. The runtime normalizes total monetary metrics to base currency and share counts to individual shares before deriving market cap, enterprise value, P/B, P/S, or EV/EBITDA. A Web Research financial number with no explicit unit/scale, an invalid scale, or a currency that does not match the resolved instrument currency is persisted as evidence but excluded from valuation calculations, leaving the result `PARTIAL` rather than guessing.

The helper `scripts/run_live_equity_research.py` can execute a structured bundle in a new isolated run. It never writes `personal.db`.

Example shape:

```json
{
  "responses": [
    {
      "intent": "LATEST_CURRENT_DATA",
      "query": "FANUC 6954 JPX latest timestamped market price",
      "hits": [
        {
          "source_name": "JPX",
          "source_url": "https://example.invalid/quote",
          "title": "timestamped quote",
          "value": "6000",
          "unit": "JPY/share",
          "currency": "JPY",
          "observed_at": "2026-08-14T09:59:00+09:00",
          "source_tier": 1,
          "source_kind": "official_exchange"
        }
      ]
    }
  ]
}
```

The exact query string in the bundle must match the query used by the runtime. `EquityResearchSpec.market_query` and `fundamentals_query` can be supplied explicitly when deterministic matching is preferred.
