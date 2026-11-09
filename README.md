# spendlens

## Categorization providers

Each transaction is categorized by the first step that knows its merchant:

1. **Your cache.** Categories remembered for your merchants, including your own corrections.
2. **Keyword rules** in `backend/app/categorization/rules.py`.
3. **An LLM provider**, for whatever is left. Unknown merchants are sent once each, in batches.

Pick the provider with `LLM_PROVIDER` in `.env`:

| `LLM_PROVIDER` | What it does |
| --- | --- |
| `fake` (default) | Offline and deterministic. Used by the tests; good for local development. |
| `gemini` | Calls the Gemini API. Needs `GEMINI_API_KEY`; `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`. |

With `LLM_PROVIDER=gemini` and no key, the API refuses to start.

Gemini also gets a one-line definition of each category, from `CATEGORY_DEFINITIONS` in
`backend/app/categorization/categories.py`. Those definitions set conventions such as
"postage and government services are Other" and "liquor stores are Shopping". Edit
them to change how merchants are categorized, then rerun the evaluation below.

**What is sent.** Only the normalized merchant names (such as `TIM HORTONS`) and the
category list. Amounts, dates, card numbers and account details never leave the app.
On Gemini's free tier, Google may use what you send to improve its products.

**When Gemini fails.** A timeout, HTTP error, rate limit or malformed reply never
fails an upload. That batch's merchants are saved as `Other` with low confidence and
`needs_review` set, and they are not cached, so they are retried on the next upload.
Rate limits and server errors get one retry after a short wait. The API key is sent
in a header and is never logged.

## Correcting categories

`PATCH /transactions/{id}` with `{"category": "Groceries", "apply_to_merchant": true}`
sets a transaction's category. It returns the updated transaction plus `also_updated`,
the number of other transactions changed.

- **The transaction** gets the category with `category_source = "user"`, confidence 1.0
  and `needs_review` cleared.
- **Your merchant cache** gets a `user` entry for the transaction's merchant (for
  example `TIM HORTONS`). Uploads check your cache before the rules and the LLM, and
  an LLM answer never overwrites a `user` entry, so every later upload of that merchant
  gets your category without asking the model. Correcting the same merchant again
  replaces the entry.
- **With `apply_to_merchant` (the default)**, your other transactions from the same
  merchant change too. Transfers are skipped, and so are rows you corrected yourself,
  so an earlier deliberate choice is never overwritten. With `false`, only that
  transaction changes, but the merchant is still remembered for future uploads.

All three changes happen in one database transaction. Corrections are per user and
never affect anyone else's categories or cache. Transfers (card payments) can't be
recategorized (400), and the category must be one of the fixed categories (422).
Dashboards and the assistant read the transaction rows, so they reflect corrections
straight away.

To build a review queue, `GET /transactions` takes `needs_review=true` and
`category=<name>` filters alongside `limit` and `offset`.

## Question assistant

`POST /assistant/ask` with `{"question": "How much did I spend on dining last month?"}`
returns `{"answer": ..., "tool_calls": [...]}`, listing the tools that were run.

**Design.** The model never sees your transactions. It can only call four read-only
tools, which are thin wrappers over the same functions the dashboard uses
(`backend/app/queries.py`): `spending_summary`, `spending_by_category`,
`spending_by_month` and `top_merchants`.
- The model may set only `start`, `end` and, for `top_merchants`, `limit`. The server
  always supplies the signed-in user's id, and the model has no way to name an account,
  so a question can only ever read your own data.
- Every argument is checked on the server. A bad call, such as an unknown argument,
  an invalid date, `end` before `start` or a `limit` outside 1–50, is sent back to the
  model as an error so it can correct itself.
- The loop is bounded: at most 4 model round trips, then a polite "I couldn't answer
  that".
- The system prompt includes today's date, so "last month" resolves correctly. It
  tells the model to answer only from tool results, to convert cents to dollars, and
  to treat the question and merchant names as data, not instructions.

The assistant uses the same `LLM_PROVIDER` setting as categorization: `fake` is a
scripted, offline assistant, and `gemini` uses Gemini function calling with the same
key handling, timeout and retry.

**What is sent to the model.** Your question, plus the aggregate tool results: totals
in cents, transaction counts, dates in the range, category names and merchant names.
Raw descriptions, individual transactions, card numbers and account details are
never sent.

**Failures.** If Gemini times out, errors or is rate limited (after one retry), the
endpoint returns 503 with a short message. Blocked or malformed output returns 200
with "I couldn't answer that". Neither includes a stack trace. Logs record the
question's length and the tool names, never the question text or the API key.

## Evaluating the categorizer

`eval/run_eval.py` measures how well categorization matches your hand labels in
`eval/labeled_merchants.csv` (columns `description,category`). It runs each description
through the real pipeline order (normalize, then rules, then the provider) with no
cache and no database, so Postgres doesn't need to be running.

```bash
python eval/run_eval.py                          # uses LLM_PROVIDER, default fake
set -a; . ./.env; set +a; python eval/run_eval.py   # with your Gemini settings
python eval/run_eval.py --json                   # machine-readable output
```

The script prints a table and writes the same report to
`eval/results/<provider>-<date>.md`. That folder is git-ignored, so reports stay local.
The two eval CSVs are committed, so CI runs the rules guard below.

The file is checked before anything runs: every category must be one of the fixed
categories, and descriptions must be non-blank and unique. The script reports every
problem with its line number and changes nothing.

**Reading the numbers**
- **Overall / Rules / Provider:** accuracy over all rows, and within the rows each
  layer handled. `Correct` counts only scored rows, so it always matches `Accuracy`.
  The `Failed` column beside it shows rows whose provider batch got no answer. With the `fake` provider, only the Rules line is meaningful. The fake
  calls most merchants `Other` at 0.4 by design.
- **Confident vs Flagged needs_review:** accuracy of rows above and below the review
  threshold (0.7). Confident rows should be very accurate. Flagged rows are the ones
  you will be asked to check.
- **Wrong answers flagged (recall):** of the wrong answers, how many were flagged for
  review. A wrong answer that isn't flagged goes into your totals silently, so this is
  the number to watch.
- **Most common mistakes / Wrong answers:** where to look when adding rules or
  fixing normalization.
- **Failed rows:** rows whose provider batch got no answer (timeout, HTTP error, rate
  limit, malformed reply). They are left out of every accuracy figure rather than
  counted as wrong.
- **Should-flag check:** each description in `eval/should_flag.csv` is ambiguous on
  purpose. The report says "flagged X of N" and lists any that came back confident.
  These rows don't count toward accuracy.

The Run table records the provider, model, temperature, date, row counts, the
review threshold, a hash of each input file and the git commit, so two reports can be
compared fairly.

`tests/test_eval.py` checks the harness on a built-in sample with the fake provider,
so CI needs no key. It also guards the rules: on the rows your rules match, they must
stay at or above 95% accuracy and 82 correct (currently 100%, 86 of 86). That test skips when the labeled file isn't present.


### Results (gemini-3.5-flash-lite, 2026-11-08)

| Set | Rows | Accuracy | Notes |
|---|---|---|---|
| Tuning set (`eval/labeled_merchants.csv`) | 165 | 98.2% | Rules and prompt were tuned using this set, so it is optimistic |
| Held-out set (`eval/holdout.csv`) | 30 | 96.7% | Written before the run and not used for tuning |

Rules handled 20% of the held-out rows (5 of 6 correct); the model handled
the rest (24 of 24 correct).

**Known weaknesses**
- Mistakes made with high confidence are not flagged for review (0 of 4
  wrong answers across both sets were flagged).
- Rules for brands with several services can be wrong: `UBER* ONE
  MEMBERSHIP` matched the Uber rule and was categorized as Transport.
- Descriptions with little information (`SP *CLASS NOTES ONLINE`) can get a
  confident guess instead of a review flag.

The held-out set is small, so one row is worth about 3 percentage points.