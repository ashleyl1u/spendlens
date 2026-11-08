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
