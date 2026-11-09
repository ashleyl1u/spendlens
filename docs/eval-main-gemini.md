# Categorizer evaluation

## Run

| Setting | Value |
|---|---|
| Provider | gemini |
| Model | gemini-3.5-flash-lite |
| Temperature | 0 |
| Date | 2026-11-09 (run at 2026-11-09T17:31:53+00:00) |
| Rows | 166 labeled, 2 should-flag |
| Review threshold | confidence < 0.7 |
| Batch size | 50 |
| Git commit | fcda238 (uncommitted changes) |
| labeled file | eval/labeled_merchants.csv (sha256 431c503b01a8) |
| should_flag file | eval/should_flag.csv (sha256 71c3e8c690fe) |

## Accuracy

| Slice | Correct | Failed | Accuracy |
|---|---|---|---|
| Overall | 164/166 | 0 | 98.8% |
| Rules | 88/88 | 0 | 100.0% |
| Provider | 76/78 | 0 | 97.4% |
| Confident (>= 0.7) | 164/166 | - | 98.8% |
| Flagged needs_review | 0/0 | - | n/a |
| Wrong answers flagged (recall) | 0/2 | - | 0.0% |

## Most common mistakes

| Expected | Got | Count |
|---|---|---|
| Entertainment | Subscriptions | 1 |
| Health | Shopping | 1 |

## Wrong answers (2)

| Description | Merchant | Expected | Got | Source | Confidence |
|---|---|---|---|---|---|
| PAYPAL *STEAMGAMES | STEAMGAMES | Entertainment | Subscriptions | llm | 0.95 |
| WELL.CA TORONTO | WELL.CA | Health | Shopping | llm | 0.95 |

## Should-flag check

flagged 2 of 2
