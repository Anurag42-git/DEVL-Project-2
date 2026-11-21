# FRONTEND PLAN — Transaction Anomaly and Refund Investigation

## Goal
Replace the Streamlit UI with a production-style FastAPI + React/TypeScript frontend while
preserving all existing detection logic and the 56 passing backend tests. The legacy Streamlit
app is moved to `legacy/` unchanged.

## Step 0 — Data/KPI fix (do first, no detection redesign)
Findings from the current dataset (1,448 ledger rows):
- Review queue has **1,462 rows**, but only **1,392 have `record_type == "transaction"`**.
  The remaining rows are customer/device records. The overview KPI wrongly used `len(queue)`.
- More importantly, **1,336 of 1,392 transaction flags are `FAST_REFUND`**: transactions with no
  refund get `fast_refund_minutes = NaN` in `src/indicators.py`, but
  `IndicatorResult.all_records()` calls `fillna(0)`, so `0 <= 10` triggers the rule.
- Current distinct flagged-transaction rate is **96.1%** (target 5–15%).

Fix:
1. Preserve missing indicator values (`NaN`) in `IndicatorResult.all_records()` so `_compare()`
   rejects them; keep `0` only for genuinely observed values.
2. Add `distinct_flagged_transactions()` / `flagged_transaction_rate()` helpers in
   `src/scoring.py` and use them for KPIs (never `len(queue)`).
3. Re-measure flag rate, precision and recall. Tune `config.yaml` thresholds only if the rate
   is still outside 5–15%, keeping injected-issue recall reasonable (assert in tests).
4. Add tests: no-refund transactions are not `FAST_REFUND`; flag count ≤ ledger count;
   one flag carries multiple reason codes; flag rate within configured band; recall retained.

## Architecture
```
frontend/ (React + TS + Vite + Tailwind + shadcn-style Radix components)
   |  VITE_API_URL (env, default http://localhost:8000)
   v
api/ (FastAPI, CORS localhost:5173/3000, Pydantic v2 models)
   |  api/state.py: run_pipeline() once, cache PipelineResult in memory, POST /api/reload
   v
src/ pipeline + scoring + review_store + report (unchanged detection rules)
   v
data/*.csv + data/review.db + reports/
```

## API contract (`/api` prefix)
All responses are JSON except downloads. All list endpoints use
`{items, total, page, page_size, ...facets}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | service status, cache fingerprint, generated_at |
| POST | `/api/reload` | re-run pipeline from CSVs and refresh cache |
| GET | `/api/overview` | KPIs (transactions, captured, refund ratio, distinct flagged transactions + %, pending reviews), daily series, reason counts, priority distribution, refund-ratio trend, top-5 needs-attention, conservation check, disclaimer |
| GET | `/api/ledger` | `search, status, customer, merchant, min_amount, max_amount, sort_by, sort_dir, page, page_size` |
| GET | `/api/transactions/{id}` | ledger row + raw events + refunds + status history + indicators + reasons + notes + lifecycle timeline |
| GET | `/api/review-queue` | `search, priority[], reason[], outcome[], from_date, to_date, sort_by, sort_dir, page, page_size`; each item includes reason chips + outcome |
| POST | `/api/review/{id}/outcome` | `{outcome, reviewer, notes}`; notes required for follow_up/escalated; returns updated item |
| GET | `/api/audit-trail/{id}` | who/what/when rows |
| GET | `/api/data-quality` | rule summary + violation examples + state machine |
| GET | `/api/report` | structured report sections + detection quality |
| GET | `/api/report/download/{format}` | `md`, `html`, `csv` file responses |

Pydantic models in `api/schemas.py`; all numeric amounts serialized as numbers with string
formatted values in the UI using tabular numerals. No response text uses prohibited labels.

## Pages & components
Pages (React Router): `/overview`, `/review`, `/ledger`, `/data-quality`, `/report`.

Shared components: `AppShell` (collapsible sidebar + top bar + global search + theme toggle),
`Disclaimer`, `KpiCard`, `Skeleton`, `EmptyState`, `ErrorState`, `PriorityBadge`, `OutcomeBadge`,
`ReasonChip`, `ScoreBar`, `ThemeProvider`, `FilterBar`, `DataTable` (TanStack Table + virtual rows),
`Pagination`, `DetailPanel` (Radix Dialog slide-over), `Toast` (sonner).

Highlights:
- **Overview**: 5 KPI cards with delta vs previous period, area chart, composite captured/refunded
  chart, horizontal reason bar, priority donut, refund-ratio trend with threshold line, needs-attention list.
- **Review Queue**: master-detail. Left virtualized sortable table with badges/chips, filters, bulk
  select and bulk outcome. Right slide-over with score gauge, reasons + actual-vs-threshold bars,
  lifecycle timeline, entity context, raw events + JSON toggle, outcome form (optimistic update +
  toast) and audit trail. Keyboard shortcuts J/K/Enter/1-4.
- **Ledger**: dense virtualized table, column visibility, CSV export, expandable raw-event panel.
- **Data Quality**: severity cards, rules table with expandable examples, violations bar chart.
- **Audit Report**: rendered sections, MD/HTML/CSV downloads, print stylesheet.

Design system: dark-first `#0B0D12`, indigo/violet accent, 8px grid, rounded-xl cards, Inter,
tabular numerals, 150–200ms transitions, semantic priority/outcome colors, WCAG AA, responsive.

## Milestones
- [x] M0 — Fixed NaN→0 fast-refund bug (flag rate 96.1% → 13.1%, precision 11.8% → 59.5%, recall 100%), distinct-transaction KPI helpers + tests, Streamlit moved to `legacy/`; 60 tests pass.
- [x] M1 — FastAPI backend: cached pipeline state, Pydantic schemas, 12 endpoints + bulk outcome, CORS, 7 passing endpoint tests; `requirements.txt` updated.
- [x] M2 — Frontend foundation: Vite + TS strict, Tailwind dark/light tokens, shadcn-style Radix components, collapsible shell + global search + theme toggle, TanStack Query/Router, env-based API URL; frontend build passes.
- [x] M3 — Overview (5 KPIs, 5 charts, needs-attention list) and Data Quality (severity cards, expandable rules, violations chart, state machine) pages; frontend build passes.
- [x] M4 — Review Queue master-detail (virtualized TanStack table, filters, score bars, reason chips, slide-over with reasons/timeline/context/raw events/JSON, outcome form, audit trail, bulk outcomes, J/K/Enter/1-4 shortcuts); build passes.
- [x] M5 — Ledger (virtualized table, filters, column visibility, CSV export, raw-event drill-down) and Audit Report (rendered sections, downloads, detection quality, print styles); build passes.
- [x] M6 — 4 Vitest/RTL tests pass (queue filters + review form), Makefile + PowerShell dev script, README rewritten with mermaid diagram, chunk-split production build, both servers started and verified (API health/overview/queue + Vite HTTP 200); 67 backend tests pass.
- [x] M7 — Deployment: FastAPI serves built SPA + API from one origin (`api/static.py`), config-driven static dir, `REVIEW_DB_PATH` env override, multi-stage Dockerfile + Compose with persistent review volume, `make serve` / `scripts/serve.ps1`, `DEPLOYMENT.md`; production server verified (SPA/routes/assets/API/docs HTTP 200, bad API 404), 70 backend tests pass.

After each milestone: run backend tests (`python -m pytest -q`) and `npm run build` (from M2 onward).
