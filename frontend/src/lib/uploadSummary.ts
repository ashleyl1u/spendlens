import type { UploadResult } from "./types";

function plural(count: number, one: string, many = `${one}s`) {
  return `${count.toLocaleString("en-CA")} ${count === 1 ? one : many}`;
}

/** An upload result in plain words, one sentence per line. */
export function describeUpload(result: UploadResult): string[] {
  const { inserted, skipped_duplicates: skipped, total_rows: total } = result;
  const lines = [
    inserted === 0
      ? `No new transactions: all ${plural(total, "row")} in the file were already saved.`
      : `Added ${plural(inserted, "new transaction")} from ${plural(total, "row")} in the file.`,
  ];
  if (skipped > 0 && inserted > 0) {
    lines.push(`Skipped ${plural(skipped, "duplicate")} that ${skipped === 1 ? "was" : "were"} already saved.`);
  }
  if (inserted > 0) {
    const by = result.categorized_by;
    lines.push(
      `Categorized ${plural(by.rule ?? 0, "transaction")} with built-in rules, ` +
        `${(by.cache ?? 0).toLocaleString("en-CA")} from categories you or the model chose before, ` +
        `and ${(by.llm ?? 0).toLocaleString("en-CA")} by the model.`,
    );
  }
  return lines;
}
