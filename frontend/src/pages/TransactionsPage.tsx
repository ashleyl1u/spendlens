import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { EmptyState, ErrorMessage, Loading } from "../components/Status";
import { api } from "../lib/api";
import {
  applyCorrection,
  confirmLabel,
  correctionErrorMessage,
  describeConfidence,
  describeConfirmation,
  describeCorrection,
  sourceLabel,
} from "../lib/corrections";
import { formatDay } from "../lib/dates";
import { notifyTransactionsChanged } from "../lib/events";
import { formatCents } from "../lib/money";
import type { CorrectedTransaction, Transaction, TransactionPage } from "../lib/types";
import { useAsync } from "../lib/useAsync";
import { useCategories } from "../lib/useCategories";

const PAGE_SIZE = 25;
type Tab = "review" | "all";
const TABS: { id: Tab; label: string }[] = [
  { id: "review", label: "Needs review" },
  { id: "all", label: "All" },
];

export function TransactionsPage() {
  // Tab, category filter and page live in the URL, so refresh and Back keep them.
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "all" ? "all" : "review";
  const category = params.get("category") ?? "";
  const offset = Math.max(0, Number(params.get("offset")) || 0);

  const categories = useCategories();
  const page = useAsync(
    (signal) =>
      api<TransactionPage>("/transactions", {
        query: {
          limit: PAGE_SIZE,
          offset,
          needs_review: tab === "review" ? true : undefined,
          category: category || undefined,
        },
        signal,
      }),
    [tab, category, offset],
  );

  // Rows are copied locally so a correction can update or remove them in place,
  // without reloading the list and losing the reader's place.
  const [rows, setRows] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  // Depend on the fetched data itself, not on `page`: useAsync returns a new object on
  // every render, and copying on each render would undo every local correction.
  const fetched = page.status === "success" ? page.data : null;
  useEffect(() => {
    if (fetched) {
      setRows(fetched.items);
      setTotal(fetched.total);
    }
  }, [fetched]);

  const [applyToMerchant, setApplyToMerchant] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const messageRef = useRef<HTMLParagraphElement>(null);
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ review: null, all: null });

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next);
    setMessage(null);
  }

  function onTabKey(event: KeyboardEvent, current: Tab) {
    // Arrow keys move between tabs, as in the WAI-ARIA tabs pattern.
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const index = TABS.findIndex((t) => t.id === current);
    const next = TABS[(index + (event.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length].id;
    update({ tab: next === "review" ? null : next, offset: null });
    tabRefs.current[next]?.focus();
  }

  function onCorrected(result: CorrectedTransaction, nextFocus: HTMLElement | null, kind: SaveKind) {
    // A confirmation is the same correction on the server, so the rows change the same way.
    const outcome = applyCorrection(rows, result, applyToMerchant, tab === "review");
    setRows(outcome.rows);
    setTotal((t) => t - outcome.removed);
    setMessage(kind === "confirm" ? describeConfirmation(result) : describeCorrection(result, applyToMerchant));
    notifyTransactionsChanged();
    if (tab === "review") {
      // The row is gone; keep keyboard focus somewhere sensible.
      requestAnimationFrame(() => (nextFocus && nextFocus.isConnected ? nextFocus : messageRef.current)?.focus());
      // Rows from the same merchant on other pages left too, which this page can't
      // see, so ask the server for the true count.
      api<TransactionPage>("/transactions", {
        query: { needs_review: true, category: category || undefined, limit: 1 },
      })
        .then((counted) => {
          setTotal(counted.total);
          // The page emptied but more rows remain: fetch the next ones.
          if (outcome.rows.length === 0 && counted.total > 0) page.reload();
        })
        .catch(() => undefined);
    }
  }

  return (
    <>
      <h1>Transactions</h1>
      <p className="lede">
        Check the categories spendlens chose. A correction is remembered for the merchant, so
        future uploads use it too.
      </p>

      <div role="tablist" aria-label="Which transactions" className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            ref={(el) => (tabRefs.current[t.id] = el)}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="transactions-panel"
            tabIndex={tab === t.id ? 0 : -1}
            className="tab"
            onClick={() => update({ tab: t.id === "review" ? null : t.id, offset: null })}
            onKeyDown={(e) => onTabKey(e, t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <section id="transactions-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="card">
        <div className="toolbar">
          <div className="field field-inline">
            <label htmlFor="category-filter">Category</label>
            <select
              id="category-filter"
              value={category}
              onChange={(e) => update({ category: e.target.value || null, offset: null })}
            >
              <option value="">All categories</option>
              {categories.status === "success" &&
                categories.data.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
            </select>
          </div>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={applyToMerchant}
              onChange={(e) => setApplyToMerchant(e.target.checked)}
            />
            Apply to all transactions from this merchant
          </label>
        </div>

        <p ref={messageRef} tabIndex={-1} className={message ? "status status-success" : "visually-hidden"} role="status">
          {message}
        </p>

        {categories.status === "error" && (
          <ErrorMessage error={`Couldn't load the category list. ${categories.error.message}`} onRetry={categories.reload} />
        )}
        {page.status === "loading" && <Loading label="Loading transactions…" />}
        {page.status === "error" && <ErrorMessage error={page.error} onRetry={page.reload} />}
        {page.status === "success" && rows.length === 0 && <NoRows tab={tab} filtered={Boolean(category)} />}
        {page.status === "success" && rows.length > 0 && (
          <>
            <table className="transactions">
              <caption className="visually-hidden">
                {tab === "review" ? "Transactions that need review" : "All transactions"}, newest first
              </caption>
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Description</th>
                  <th scope="col" className="num">Amount</th>
                  <th scope="col">Category</th>
                  <th scope="col">Decided by</th>
                  <th scope="col">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <TransactionRow
                    key={`${row.id}-${row.category}`}
                    row={row}
                    categories={categories.status === "success" ? categories.data : null}
                    applyToMerchant={applyToMerchant}
                    reviewMode={tab === "review"}
                    onCorrected={onCorrected}
                  />
                ))}
              </tbody>
            </table>
            <Pagination
              offset={offset}
              shown={rows.length}
              total={total}
              onPage={(next) => update({ offset: next ? String(next) : null })}
            />
          </>
        )}
      </section>
    </>
  );
}

function NoRows({ tab, filtered }: { tab: Tab; filtered: boolean }) {
  if (filtered) {
    return <EmptyState title="No transactions in this category">Choose “All categories” to see the rest.</EmptyState>;
  }
  if (tab === "review") {
    return (
      <EmptyState title="Nothing to review">
        <p>Every category is one spendlens is confident about, or one you've checked. Nice.</p>
      </EmptyState>
    );
  }
  return (
    <EmptyState title="No transactions yet">
      <p>
        <Link to="/upload">Upload a statement</Link> to get started.
      </p>
    </EmptyState>
  );
}

type SaveKind = "correct" | "confirm";

function TransactionRow({
  row,
  categories,
  applyToMerchant,
  reviewMode,
  onCorrected,
}: {
  row: Transaction;
  categories: string[] | null;
  applyToMerchant: boolean;
  /** In Needs review, a row can be confirmed as-is with "Looks right". */
  reviewMode: boolean;
  onCorrected: (result: CorrectedTransaction, nextFocus: HTMLElement | null, kind: SaveKind) => void;
}) {
  const [choice, setChoice] = useState(row.category ?? "");
  const [busy, setBusy] = useState<SaveKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rowRef = useRef<HTMLTableRowElement>(null);
  const confidence = describeConfidence(row.confidence);
  const selectId = `category-${row.id}`;
  const changed = choice !== (row.category ?? "");

  // "Looks right" sends the category the row already has. The backend treats that as a
  // full correction: source "user", confidence 1.0, review cleared, merchant remembered.
  async function save(kind: SaveKind) {
    const category = kind === "confirm" ? (row.category ?? "") : choice;
    setBusy(kind);
    setError(null);
    try {
      const result = await api<CorrectedTransaction>(`/transactions/${row.id}`, {
        method: "PATCH",
        body: { category, apply_to_merchant: applyToMerchant },
      });
      // Where focus should go if this row disappears: the next row's dropdown.
      const next = rowRef.current?.nextElementSibling?.querySelector<HTMLElement>("select") ?? null;
      onCorrected(result, next, kind);
    } catch (err) {
      setError(correctionErrorMessage(err, category));
      setBusy(null);
    }
  }

  return (
    <tr ref={rowRef} className={row.needs_review ? "needs-review" : undefined}>
      <td data-label="Date">{formatDay(row.posted_date)}</td>
      <td data-label="Description">
        <span className="merchant">{row.merchant ?? "—"}</span>
        <span className="raw-description">{row.raw_description}</span>
      </td>
      <td data-label="Amount" className="num">
        {formatCents(row.amount_cents)}
      </td>
      <td data-label="Category">
        {row.is_transfer ? (
          <span>
            Transfer <span className="hint-inline">(card payment, not spending)</span>
          </span>
        ) : (
          <div className="category-edit">
            <label htmlFor={selectId} className="visually-hidden">
              Category for {row.merchant ?? row.raw_description} on {formatDay(row.posted_date)}
            </label>
            <select
              id={selectId}
              value={choice}
              disabled={!categories || busy !== null}
              onChange={(e) => {
                setChoice(e.target.value);
                setError(null);
              }}
            >
              {!row.category && <option value="">Uncategorized</option>}
              {(categories ?? (row.category ? [row.category] : [])).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            {changed && (
              <button
                type="button"
                className="button button-primary button-small"
                onClick={() => save("correct")}
                disabled={busy !== null}
              >
                {busy === "correct" ? "Saving…" : "Save"}
              </button>
            )}
            {reviewMode && !changed && row.category && (
              <button
                type="button"
                className="button button-secondary button-small"
                onClick={() => save("confirm")}
                disabled={busy !== null}
                aria-label={confirmLabel(row.category, row.merchant)}
              >
                {busy === "confirm" ? "Confirming…" : "Looks right"}
              </button>
            )}
          </div>
        )}
        {error && (
          <p className="row-error" role="alert">
            {error}
          </p>
        )}
      </td>
      <td data-label="Decided by">{sourceLabel(row.category_source)}</td>
      <td data-label="Confidence">
        <span className={`confidence confidence-${confidence.level}`}>
          <span aria-hidden="true" className="confidence-mark" />
          {confidence.label}
          {row.needs_review && <span className="review-flag"> · needs review</span>}
        </span>
      </td>
    </tr>
  );
}

function Pagination({
  offset,
  shown,
  total,
  onPage,
}: {
  offset: number;
  shown: number;
  total: number;
  onPage: (offset: number) => void;
}) {
  if (total <= PAGE_SIZE && offset === 0) {
    return <p className="hint">{total === 1 ? "1 transaction" : `${total} transactions`}</p>;
  }
  return (
    <nav className="pagination" aria-label="Pages">
      <button
        type="button"
        className="button button-secondary"
        disabled={offset === 0}
        onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))}
      >
        Previous
      </button>
      <p className="hint" aria-live="polite">
        {offset + 1}–{offset + shown} of {total}
      </p>
      <button
        type="button"
        className="button button-secondary"
        disabled={offset + shown >= total}
        // Continue after the rows actually shown: in Needs review, corrected rows leave
        // the list, so the next rows have moved up and offset + PAGE_SIZE would skip some.
        onClick={() => onPage(offset + shown)}
      >
        Next
      </button>
    </nav>
  );
}
