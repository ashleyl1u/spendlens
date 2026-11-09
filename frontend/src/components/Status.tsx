import type { ReactNode } from "react";

/** Loading, error and empty states, announced to screen readers. */

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="status status-loading" role="status" aria-live="polite">
      {label}
    </p>
  );
}

export function ErrorMessage({ error, onRetry }: { error: Error | string; onRetry?: () => void }) {
  return (
    <div className="status status-error" role="alert">
      <p>{typeof error === "string" ? error : error.message}</p>
      {onRetry && (
        <button type="button" className="button button-secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="status status-empty">
      <p className="status-title">{title}</p>
      {children}
    </div>
  );
}
