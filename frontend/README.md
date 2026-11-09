# spendlens frontend

A small React app for spendlens: sign up and log in, add card accounts, upload RBC
statements, and see a spending dashboard.

Built with Vite, React, TypeScript, React Router and Recharts, with plain CSS.

## Running it

1. Start the backend on port 8000 (from the repo root; see the main README):

   ```bash
   docker compose up
   ```

   or run `uvicorn app.main:app --port 8000` from `backend/` with your `.env` loaded.

2. In another terminal, start the frontend:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

3. Open http://localhost:5173.

The Vite dev server proxies `/auth`, `/accounts`, `/uploads`, `/transactions`,
`/dashboard` and `/assistant` to `http://127.0.0.1:8000`, so the browser only ever
talks to one origin and the backend needs no CORS setup. To use a backend on another
port, set `SPENDLENS_API_URL`, for example `SPENDLENS_API_URL=http://127.0.0.1:8001 npm run dev`. A few of those paths are
also pages in the app (`/accounts`). The proxy sends browser navigations, which ask
for HTML, to the app and only API calls, which ask for JSON, to the backend.

## Other commands

```bash
npm test           # Vitest: the money formatter, token handling, upload wording
npm run typecheck  # TypeScript, no output files
npm run build      # type-check and build to dist/
```

`npm run build` makes a static bundle, but nothing serves it with an API proxy yet.
For now, use `npm run dev`.

## How it works

- **Signing in.** The login form posts `username` (your email) and `password` as a
  form body to `/auth/login`. The token is kept in memory and in `localStorage`, so
  a refresh keeps you signed in. An expired token is dropped on load. Any 401 from
  the API clears the token and returns you to the login page. The token is the only
  credential in the frontend; there are no API keys.
- **Money.** The API sends integer cents. Every amount on screen goes through
  `formatCents` in `src/lib/money.ts`, which formats Canadian dollars with
  `Intl.NumberFormat`.
- **Charts.** Each chart is a single series in one color, checked for at least 3:1
  contrast in light and dark mode. Every value is also shown as text in a table.
  The monthly chart can be explored with the arrow keys once focused. The category
  chart can't (Recharts 2 has no keyboard support for horizontal bars), so it isn't
  a tab stop, and the table beside it carries every value. Text colors meet 4.5:1.
- **Dates.** The dashboard's From and To dates are kept in the URL, so a refresh or a
  shared link shows the same range.
