/**
 * Wording and rules for category corrections, kept apart from the page so they can be
 * unit tested. They mirror the backend (app/categorization/corrections.py).
 */

import { ApiError } from "./api";
import type { CategorySource, CorrectedTransaction, Transaction } from "./types";

/** Below this the backend sets needs_review (REVIEW_THRESHOLD in categories.py). */
export const REVIEW_THRESHOLD = 0.7;
const HIGH_CONFIDENCE = 0.9;

/** How a category was decided, in words a person would use. */
export function sourceLabel(source: CategorySource | null): string {
  switch (source) {
    case "rule":
      return "Rule";
    case "cache":
      return "Remembered";
    case "llm":
      return "Model";
    case "user":
      return "You";
    default:
      return "Not categorized";
  }
}

export type ConfidenceLevel = "high" | "medium" | "low" | "none";

/**
 * Confidence as a level and a text label, so it never relies on color alone:
 * "High · 95%", "Medium · 80%", "Low · 60%". Low is what gets flagged for review.
 */
export function describeConfidence(confidence: number | null): {
  level: ConfidenceLevel;
  label: string;
} {
  if (confidence === null || !Number.isFinite(confidence)) return { level: "none", label: "—" };
  const percent = `${Math.round(confidence * 100)}%`;
  if (confidence >= HIGH_CONFIDENCE) return { level: "high", label: `High · ${percent}` };
  if (confidence >= REVIEW_THRESHOLD) return { level: "medium", label: `Medium · ${percent}` };
  return { level: "low", label: `Low · ${percent}` };
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** The result of a correction in plain words. */
export function describeCorrection(
  result: CorrectedTransaction,
  applyToMerchant: boolean,
): string {
  const category = result.category ?? "the new category";
  if (!result.merchant) return `Updated this transaction to ${category}.`;
  if (!applyToMerchant) {
    return (
      `Updated this transaction to ${category}. ` +
      `Future ${result.merchant} transactions will also be ${category}.`
    );
  }
  const updated = 1 + result.also_updated;
  return `Updated ${plural(updated, "transaction")} from ${result.merchant} to ${category}.`;
}

/** The result of confirming a category that was already right, in plain words. */
export function describeConfirmation(result: CorrectedTransaction): string {
  const category = result.category ?? "the category";
  if (!result.merchant) return `Confirmed ${category} for this transaction.`;
  const others = result.also_updated;
  if (others === 0) return `Confirmed ${category} for ${result.merchant}.`;
  return (
    `Confirmed ${category} for ${result.merchant}, and set ${plural(others, "other transaction")} ` +
    `from it to ${category}.`
  );
}

/**
 * The "Looks right" button's accessible name. It starts with the visible text, so
 * voice-control users can say "click Looks right", then says what will be confirmed.
 */
export function confirmLabel(category: string, merchant: string | null): string {
  return `Looks right: confirm ${category} for ${merchant ?? "this transaction"}`;
}

/** A clear message for a failed correction. */
export function correctionErrorMessage(error: unknown, category: string): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  switch (error.status) {
    case 400:
      return "Card payments and other transfers can't be given a spending category.";
    case 404:
      return "That transaction no longer exists. Refresh the list and try again.";
    case 422:
      return `“${category}” isn't one of spendlens's categories. Choose one from the list.`;
    default:
      return error.message;
  }
}

/**
 * Apply a successful correction to the rows on screen, the same way the backend does:
 * the corrected row takes the response; with applyToMerchant, the user's other rows
 * from that merchant follow, except transfers and rows the user already corrected.
 *
 * In the review tab, every row that changed no longer needs review and leaves the list.
 * Returns the new rows and how many left.
 */
export function applyCorrection(
  rows: Transaction[],
  result: CorrectedTransaction,
  applyToMerchant: boolean,
  reviewOnly: boolean,
): { rows: Transaction[]; removed: number } {
  const changes = (row: Transaction) =>
    row.id === result.id ||
    (applyToMerchant &&
      result.merchant !== null &&
      row.merchant === result.merchant &&
      !row.is_transfer &&
      row.category_source !== "user");

  if (reviewOnly) {
    const kept = rows.filter((row) => !changes(row));
    return { rows: kept, removed: rows.length - kept.length };
  }
  const { also_updated: _ignored, ...corrected } = result;
  const updated = rows.map((row) => {
    if (row.id === result.id) return corrected;
    if (!changes(row)) return row;
    return {
      ...row,
      category: result.category,
      category_source: "user" as const,
      confidence: 1,
      needs_review: false,
    };
  });
  return { rows: updated, removed: 0 };
}
