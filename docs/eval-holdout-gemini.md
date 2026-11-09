# Categorizer evaluation

## Run

| Setting | Value |
|---|---|
| Provider | gemini |
| Model | gemini-3.5-flash-lite |
| Temperature | 0 |
| Date | 2026-11-08 (run at 2026-11-08T20:44:00+00:00) |
| Rows | 30 labeled, 2 should-flag |
| Review threshold | confidence < 0.7 |
| Batch size | 50 |
| Git commit | fcda238 (uncommitted changes) |
| labeled file | eval/holdout.csv (sha256 c62f15b18c6d) |
| should_flag file | eval/should_flag.csv (sha256 71c3e8c690fe) |

## Accuracy

| Slice | Correct | Failed | Accuracy |
|---|---|---|---|
| Overall | 29/30 | 0 | 96.7% |
| Rules | 5/6 | 0 | 83.3% |
| Provider | 24/24 | 0 | 100.0% |
| Confident (>= 0.7) | 29/30 | - | 96.7% |
| Flagged needs_review | 0/0 | - | n/a |
| Wrong answers flagged (recall) | 0/1 | - | 0.0% |

## Most common mistakes

| Expected | Got | Count |
|---|---|---|
| Subscriptions | Transport | 1 |

## Wrong answers (1)

| Description | Merchant | Expected | Got | Source | Confidence |
|---|---|---|---|---|---|
| UBER* ONE MEMBERSHIP | UBER | Subscriptions | Transport | rule | 0.95 |

## Should-flag check

flagged 1 of 2

Not flagged:
| Description | Merchant | Got | Source | Confidence |
|---|---|---|---|---|
| SP *CLASS NOTES ONLINE | CLASS NOTES ONLINE | Subscriptions | llm | 0.80 |
