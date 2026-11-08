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

**What is sent.** Only the normalized merchant names (such as `TIM HORTONS`) and the
category list. Amounts, dates, card numbers and account details never leave the app.
On Gemini's free tier, Google may use what you send to improve its products.

**When Gemini fails.** A timeout, HTTP error, rate limit or malformed reply never
fails an upload. That batch's merchants are saved as `Other` with low confidence and
`needs_review` set, and they are not cached, so they are retried on the next upload.
Rate limits and server errors get one retry after a short wait. The API key is sent
in a header and is never logged.

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
