import { Link, useSearchParams } from "react-router-dom";

import { CategoryChart, MonthlyChart } from "../components/Charts";
import { EmptyState, ErrorMessage, Loading } from "../components/Status";
import { api } from "../lib/api";
import { formatDay, formatMonth } from "../lib/dates";
import { formatCents } from "../lib/money";
import { formatShare } from "../lib/percent";
import type { CategoryTotal, MerchantTotal, MonthTotal, Summary } from "../lib/types";
import { useAsync } from "../lib/useAsync";

interface DashboardData {
  summary: Summary;
  categories: CategoryTotal[];
  months: MonthTotal[];
  merchants: MerchantTotal[];
}

const TOP_MERCHANTS = 10;

export function DashboardPage() {
  // Dates live in the URL, so a refresh or a shared link keeps the same view.
  const [params, setParams] = useSearchParams();
  const start = params.get("start") ?? "";
  const end = params.get("end") ?? "";
  const rangeError = start && end && end < start ? "The end date must be on or after the start date." : null;

  const dashboard = useAsync<DashboardData | null>(
    async (signal) => {
      if (rangeError) return null;
      const query = { start, end };
      const [summary, categories, months, merchants] = await Promise.all([
        api<Summary>("/dashboard/summary", { query, signal }),
        api<CategoryTotal[]>("/dashboard/by-category", { query, signal }),
        api<MonthTotal[]>("/dashboard/by-month", { query, signal }),
        api<MerchantTotal[]>("/dashboard/top-merchants", {
          query: { ...query, limit: TOP_MERCHANTS },
          signal,
        }),
      ]);
      return { summary, categories, months, merchants };
    },
    [start, end, rangeError],
  );

  function setDate(name: "start" | "end", value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  }

  const filtered = Boolean(start || end);

  return (
    <>
      <div className="page-heading">
        <h1>Dashboard</h1>
        <form className="filters" aria-label="Date range" onSubmit={(e) => e.preventDefault()}>
          <div className="field field-inline">
            <label htmlFor="start">From</label>
            <input id="start" type="date" value={start} max={end || undefined}
              onChange={(e) => setDate("start", e.target.value)} aria-invalid={Boolean(rangeError) || undefined} />
          </div>
          <div className="field field-inline">
            <label htmlFor="end">To</label>
            <input id="end" type="date" value={end} min={start || undefined}
              onChange={(e) => setDate("end", e.target.value)} aria-invalid={Boolean(rangeError) || undefined} />
          </div>
          {filtered && (
            <button type="button" className="button button-secondary" onClick={() => setParams({}, { replace: true })}>
              All time
            </button>
          )}
        </form>
      </div>
      {rangeError && <ErrorMessage error={rangeError} />}
      {!rangeError && dashboard.status === "loading" && <Loading label="Loading your spending…" />}
      {!rangeError && dashboard.status === "error" && (
        <ErrorMessage error={dashboard.error} onRetry={dashboard.reload} />
      )}
      {dashboard.status === "success" && dashboard.data && (
        <DashboardBody data={dashboard.data} filtered={filtered} />
      )}
    </>
  );
}

function DashboardBody({ data, filtered }: { data: DashboardData; filtered: boolean }) {
  const { summary, categories, months, merchants } = data;

  if (summary.transaction_count === 0) {
    return filtered ? (
      <EmptyState title="No spending in this date range">
        <p>Try a wider range, or choose “All time”.</p>
      </EmptyState>
    ) : (
      <EmptyState title="No transactions yet">
        <p>
          <Link to="/upload">Upload a statement</Link> to see where your money goes. You'll need an{" "}
          <Link to="/accounts">account</Link> first.
        </p>
      </EmptyState>
    );
  }

  return (
    <>
      <section aria-label="Summary" className="stat-grid">
        <Stat label="Total spent" value={formatCents(summary.total_spent_cents)} />
        <Stat label="Transactions" value={summary.transaction_count.toLocaleString("en-CA")} />
        <Stat
          label="Need review"
          value={summary.needs_review_count.toLocaleString("en-CA")}
          hint={summary.needs_review_count > 0 ? "Categories the app wasn't sure about" : "Nothing to check"}
        />
        <Stat
          label="Date range"
          value={summary.first_date && summary.last_date
            ? `${formatDay(summary.first_date)} – ${formatDay(summary.last_date)}`
            : "—"}
          small
        />
      </section>

      <section className="card" aria-labelledby="by-category">
        <h2 id="by-category">Spending by category</h2>
        <div className="chart-with-table">
          <CategoryChart data={categories} />
          <table className="data-table">
            <caption className="visually-hidden">Spending by category</caption>
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col" className="num">Spent</th>
                <th scope="col" className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              {categories.map((c) => (
                <tr key={c.category}>
                  <th scope="row">{c.category}</th>
                  <td className="num">{formatCents(c.total_cents)}</td>
                  <td className="num">{formatShare(c.share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">Refunds are subtracted from the category they belong to. Card payments are left out.</p>
      </section>

      <div className="two-column">
        <section className="card" aria-labelledby="by-month">
          <h2 id="by-month">Spending per month</h2>
          <MonthlyChart data={months} />
          <details className="table-toggle">
            <summary>Show as a table</summary>
            <table className="data-table">
              <caption className="visually-hidden">Spending per month</caption>
              <thead>
                <tr>
                  <th scope="col">Month</th>
                  <th scope="col" className="num">Spent</th>
                  <th scope="col" className="num">Transactions</th>
                </tr>
              </thead>
              <tbody>
                {months.map((m) => (
                  <tr key={m.month}>
                    <th scope="row">{formatMonth(m.month, "long")}</th>
                    <td className="num">{formatCents(m.total_cents)}</td>
                    <td className="num">{m.transaction_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </section>

        <section className="card" aria-labelledby="top-merchants">
          <h2 id="top-merchants">Top merchants</h2>
          <ol className="merchant-list">
            {merchants.map((m) => (
              <li key={m.merchant}>
                <span className="merchant-name">{m.merchant}</span>
                <span className="merchant-amount">{formatCents(m.total_cents)}</span>
                <span className="merchant-count">
                  {m.transaction_count} transaction{m.transaction_count === 1 ? "" : "s"}
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  );
}

function Stat({ label, value, hint, small }: { label: string; value: string; hint?: string; small?: boolean }) {
  return (
    <div className="card stat">
      <p className="stat-label">{label}</p>
      <p className={small ? "stat-value stat-value-small" : "stat-value"}>{value}</p>
      {hint && <p className="stat-hint">{hint}</p>}
    </div>
  );
}
