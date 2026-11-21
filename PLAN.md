# PLAN — Transaction Anomaly and Refund Investigation

## Goal
A monitoring application that reconciles synthetic payment lifecycles, validates data quality,
computes explainable indicators, ranks unusual activity for manual review, and produces an audit
report. **Flags are review triggers, never fraud determinations.**

## Folder structure
```
DEVL-Project-2/
├── app.py                          # Streamlit entry point = Overview page
├── pages/                          # Remaining Streamlit pages
│   ├── 2_Reconciled_Ledger.py
│   ├── 3_Review_Queue.py
│   ├── 4_Data_Quality.py
│   └── 5_Audit_Report.py
├── config.yaml                     # ALL thresholds, weights, seed, paths (no hard-coding)
├── requirements.txt
├── PLAN.md
├── README.md
├── src/
│   ├── __init__.py
│   ├── config.py                   # config loading + project-root/path resolution
│   ├── utils.py                    # IO, datetime, formatting helpers
│   ├── generate_data.py            # step 1: synthetic data + hidden ground truth
│   ├── validate.py                 # step 2: rules + explicit status state machine
│   ├── reconcile.py                # step 3: one-row-per-transaction ledger + invariant
│   ├── indicators.py               # step 4: per entity indicators / rolling windows
│   ├── scoring.py                  # step 5: transparent weighted rules -> review queue
│   ├── review_store.py             # step 5: SQLite outcomes + append-only audit trail
│   ├── pipeline.py                 # orchestration shared by app / report / tests
│   ├── dashboard.py                # shared Streamlit helpers (cached pipeline, disclaimer)
│   └── report.py                   # step 7: Markdown + HTML audit report
├── data/                           # generated CSVs (git-ignored)
│   └── .ground_truth.csv           # hidden injected-issue answer key
├── reports/                        # generated audit_report.md / .html
└── tests/                          # step 8: pytest suite
```

## Data schema
| File | Key columns |
|---|---|
| `customers.csv` | customer_id, signup_date, country, risk_segment |
| `merchants.csv` | merchant_id, category, country, onboarding_date |
| `transactions.csv` | event_id, transaction_id, customer_id, merchant_id, amount, currency, event_timestamp, event_type, status, device_id |
| `refunds.csv` | refund_id, transaction_id, refund_amount, refund_timestamp, refund_status |
| `payment_status.csv` | transaction_id, status, status_timestamp |
| `device_summary.csv` | device_id, customer_count, first_seen, last_seen, failed_attempt_count |
| `.ground_truth.csv` (hidden) | issue_id, issue_type, record_type, entity_id, expected_reason_code, severity, description, source_file, details |

Record types in the review queue: `transaction`, `customer`, `merchant`, `device`; a record's
`record_id` is the corresponding business id, which lets ground truth be matched directly.

## Module list and responsibilities
1. `generate_data.py` — seeded generation of normal activity + 15 deliberate injections:
   duplicate event ids, retry storms, partial refunds, over-refunds, invalid transitions,
   non-positive amounts, future/out-of-order timestamps, orphan references, bursts, repeated
   failures, shared devices, round amounts, fast refunds, currency mismatch.
2. `validate.py` — independent rules producing `rule | severity | count | example rows`;
   status transitions checked with an explicit config-driven state machine.
3. `reconcile.py` — deduplicate on `event_id` (idempotent), collapse retries as attempts,
   aggregate completed refunds, derive final status/attempt counts/notes, expose a
   raw-vs-ledger conservation invariant.
4. `indicators.py` — 1h/24h/7d rolling frequencies, refund ratios, failure runs/rate,
   robust MAD amount deviation, device sharing, fast refunds, round amounts, retry storms;
   every threshold read from `config.yaml`.
5. `scoring.py` + `review_store.py` — weighted rules with reason codes, plain-English
   explanations and actual-vs-threshold values; priority bands; SQLite outcomes and a full
   who/what/when audit trail. Optional IsolationForest is secondary only and off by default.
6. `dashboard.py` / `app.py` / `pages/*` — five pages, search/filter/drill-down, outcome form,
   validation examples, report downloads, persistent disclaimer.
7. `report.py` — Markdown + HTML audit report with methodology, thresholds, adjustments,
   review outcomes, limitations and ground-truth precision/recall.
8. `pipeline.py` — single source of truth for assembling all artifacts.

## Status state machine
`pending -> authorized -> captured -> partially_refunded -> refunded`, with
`failed` and `voided` terminal; self-loops allowed for repeated authorization/capture/
partial-refund events; `refunded -> captured` (etc.) is invalid.

## Milestone checklist
- [x] M0 — Read requirements, inspect environment, write this plan.
- [x] M1 — `config.yaml`, requirements, package skeleton, seeded generator + hidden ground truth; test generation (6 passed).
- [x] M2 — Validation rules + state machine + report; pytest for every rule (28 tests total pass).
- [x] M3 — Reconciliation ledger + conservation invariant; pytest for duplicates/retries/refunds (34 tests total pass).
- [x] M4 — Indicators with config thresholds; pytest for windows/MAD/aggregations (40 tests total pass).
- [x] M5 — Scoring explanations + SQLite review store; pytest for explanations/audit trail (51 tests total pass, injected-issue recall ~95%).
- [x] M6 — Streamlit dashboard (5 pages) with disclaimer; all five pages smoke-tested with AppTest.
- [x] M7 — Audit report MD/HTML with precision/recall; pytest for report content (54 tests total pass).
- [x] M8 — Full pytest run (56 passed), end-to-end command replay, live `streamlit run app.py` HTTP 200, README with mermaid diagram + limitations.

Run after each milestone: `python -m pytest -q` (and a Streamlit import smoke check from M6).
