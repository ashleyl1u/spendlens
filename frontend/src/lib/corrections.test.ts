import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import {
  applyCorrection,
  confirmLabel,
  correctionErrorMessage,
  describeConfidence,
  describeConfirmation,
  describeCorrection,
  sourceLabel,
} from "./corrections";
import type { CorrectedTransaction, Transaction } from "./types";

function row(id: number, overrides: Partial<Transaction> = {}): Transaction {
  return {
    id,
    account_id: 1,
    upload_id: 1,
    posted_date: "2024-03-05",
    amount_cents: 312,
    raw_description: "TIM HORTONS #2210 TORONTO",
    merchant: "TIM HORTONS",
    category: "Dining",
    category_source: "rule",
    confidence: 0.95,
    is_transfer: false,
    needs_review: false,
    ...overrides,
  };
}

function corrected(id: number, category: string, alsoUpdated: number, merchant: string | null = "TIM HORTONS"): CorrectedTransaction {
  return {
    ...row(id, { merchant }),
    category,
    category_source: "user",
    confidence: 1,
    needs_review: false,
    also_updated: alsoUpdated,
  };
}

describe("describeCorrection", () => {
  it("counts the corrected row plus the others from the merchant", () => {
    expect(describeCorrection(corrected(1, "Groceries", 2), true)).toBe(
      "Updated 3 transactions from TIM HORTONS to Groceries.",
    );
  });

  it("uses the singular for one transaction", () => {
    expect(describeCorrection(corrected(1, "Groceries", 0), true)).toBe(
      "Updated 1 transaction from TIM HORTONS to Groceries.",
    );
  });

  it("says future uploads are covered even when only one row changed", () => {
    expect(describeCorrection(corrected(1, "Groceries", 0), false)).toBe(
      "Updated this transaction to Groceries. Future TIM HORTONS transactions will also be Groceries.",
    );
  });

  it("handles a transaction without a merchant", () => {
    expect(describeCorrection(corrected(1, "Other", 0, null), true)).toBe(
      "Updated this transaction to Other.",
    );
  });
});

describe("describeConfirmation", () => {
  it("confirms the category for the merchant in plain words", () => {
    expect(describeConfirmation(corrected(1, "Dining", 0, "RFBT-TORONTO YONGE ST"))).toBe(
      "Confirmed Dining for RFBT-TORONTO YONGE ST.",
    );
  });

  it("mentions other transactions that apply-to-all changed", () => {
    expect(describeConfirmation(corrected(1, "Dining", 1))).toBe(
      "Confirmed Dining for TIM HORTONS, and set 1 other transaction from it to Dining.",
    );
    expect(describeConfirmation(corrected(1, "Dining", 4))).toBe(
      "Confirmed Dining for TIM HORTONS, and set 4 other transactions from it to Dining.",
    );
  });

  it("handles a transaction without a merchant", () => {
    expect(describeConfirmation(corrected(1, "Other", 0, null))).toBe(
      "Confirmed Other for this transaction.",
    );
  });
});

describe("confirmLabel", () => {
  it("starts with the visible text, then says what is confirmed", () => {
    expect(confirmLabel("Dining", "RFBT-TORONTO YONGE ST")).toBe(
      "Looks right: confirm Dining for RFBT-TORONTO YONGE ST",
    );
    expect(confirmLabel("Other", null)).toBe("Looks right: confirm Other for this transaction");
  });
});

describe("correctionErrorMessage", () => {
  it.each([
    [400, "Card payments and other transfers can't be given a spending category."],
    [404, "That transaction no longer exists. Refresh the list and try again."],
    [422, "“Pizza” isn't one of spendlens's categories. Choose one from the list."],
  ])("explains a %i", (status, message) => {
    expect(correctionErrorMessage(new ApiError(status, "server text"), "Pizza")).toBe(message);
  });

  it("passes other API errors through", () => {
    expect(correctionErrorMessage(new ApiError(0, "Can't reach the server"), "Dining")).toBe(
      "Can't reach the server",
    );
  });

  it("never shows a raw exception", () => {
    expect(correctionErrorMessage(new TypeError("x is undefined"), "Dining")).toBe(
      "Something went wrong. Please try again.",
    );
  });
});

describe("sourceLabel and describeConfidence", () => {
  it("names every source in plain words", () => {
    expect(["rule", "cache", "llm", "user", null].map((s) => sourceLabel(s as never))).toEqual([
      "Rule",
      "Remembered",
      "Model",
      "You",
      "Not categorized",
    ]);
  });

  it("gives confidence a word as well as a level", () => {
    expect(describeConfidence(0.95)).toEqual({ level: "high", label: "High · 95%" });
    expect(describeConfidence(0.9)).toEqual({ level: "high", label: "High · 90%" });
    expect(describeConfidence(0.75)).toEqual({ level: "medium", label: "Medium · 75%" });
    expect(describeConfidence(0.7)).toEqual({ level: "medium", label: "Medium · 70%" });
    expect(describeConfidence(0.6)).toEqual({ level: "low", label: "Low · 60%" });
    expect(describeConfidence(null)).toEqual({ level: "none", label: "—" });
  });
});

describe("applyCorrection", () => {
  const rows = [
    row(1, { needs_review: true, confidence: 0.6, category_source: "llm" }),
    row(2),
    row(3, { category: "Entertainment", category_source: "user", confidence: 1 }),
    row(4, { merchant: "METRO", category: "Groceries" }),
    row(5, { merchant: "TIM HORTONS", is_transfer: true, category: "Transfer" }),
  ];

  it("in All, updates the row and its merchant's other rows in place", () => {
    const { rows: next, removed } = applyCorrection(rows, corrected(1, "Groceries", 1), true, false);

    expect(removed).toBe(0);
    expect(next.map((r) => [r.id, r.category, r.category_source])).toEqual([
      [1, "Groceries", "user"],
      [2, "Groceries", "user"], // same merchant follows
      [3, "Entertainment", "user"], // the user's own earlier choice is kept
      [4, "Groceries", "rule"], // other merchant untouched
      [5, "Transfer", "rule"], // transfers never change
    ]);
    expect(next[0]).not.toHaveProperty("also_updated");
    expect(next[1]).toMatchObject({ confidence: 1, needs_review: false });
  });

  it("in All without apply-to-merchant, changes only that row", () => {
    const { rows: next } = applyCorrection(rows, corrected(1, "Groceries", 0), false, false);
    expect(next.map((r) => r.category)).toEqual(["Groceries", "Dining", "Entertainment", "Groceries", "Transfer"]);
  });

  it("in Needs review, removes every row that changed", () => {
    const review = [rows[0], row(6, { needs_review: true }), row(7, { merchant: "METRO", needs_review: true })];

    const { rows: next, removed } = applyCorrection(review, corrected(1, "Groceries", 1), true, true);

    expect(next.map((r) => r.id)).toEqual([7]);
    expect(removed).toBe(2);
  });

  it("in Needs review without apply-to-merchant, removes only that row", () => {
    const review = [rows[0], row(6, { needs_review: true })];
    const { rows: next, removed } = applyCorrection(review, corrected(1, "Groceries", 0), false, true);
    expect(next.map((r) => r.id)).toEqual([6]);
    expect(removed).toBe(1);
  });

  it("does not treat a missing merchant as a match", () => {
    const noMerchant = [row(1, { merchant: null }), row(2, { merchant: null })];
    const { rows: next } = applyCorrection(noMerchant, corrected(1, "Other", 0, null), true, false);
    expect(next.map((r) => r.category)).toEqual(["Other", "Dining"]);
  });
});
