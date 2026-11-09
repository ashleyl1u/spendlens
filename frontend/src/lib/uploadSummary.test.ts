import { describe, expect, it } from "vitest";

import { describeUpload } from "./uploadSummary";

const base = { upload_id: 1, account_id: 1 };

describe("describeUpload", () => {
  it("explains a first upload in plain words", () => {
    expect(
      describeUpload({
        ...base,
        inserted: 24,
        skipped_duplicates: 0,
        total_rows: 24,
        categorized_by: { rule: 18, cache: 0, llm: 6 },
      }),
    ).toEqual([
      "Added 24 new transactions from 24 rows in the file.",
      "Categorized 18 transactions with built-in rules, 0 from categories you or the model chose before, and 6 by the model.",
    ]);
  });

  it("explains a re-upload where everything was a duplicate", () => {
    expect(
      describeUpload({
        ...base,
        inserted: 0,
        skipped_duplicates: 24,
        total_rows: 24,
        categorized_by: { rule: 0, cache: 0, llm: 0 },
      }),
    ).toEqual(["No new transactions: all 24 rows in the file were already saved."]);
  });

  it("mentions skipped duplicates in a partial upload, with singular wording", () => {
    expect(
      describeUpload({
        ...base,
        inserted: 1,
        skipped_duplicates: 1,
        total_rows: 2,
        categorized_by: { rule: 1, cache: 0, llm: 0 },
      }),
    ).toEqual([
      "Added 1 new transaction from 2 rows in the file.",
      "Skipped 1 duplicate that was already saved.",
      "Categorized 1 transaction with built-in rules, 0 from categories you or the model chose before, and 0 by the model.",
    ]);
  });
});
