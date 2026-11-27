/** Turn the assistant's tool calls into readable lines for "How I got this". */

import { formatDay } from "./dates";
import type { ToolCall } from "./types";

const TOOL_NAMES: Record<string, string> = {
  spending_summary: "Spending summary",
  spending_by_category: "Spending by category",
  spending_by_month: "Spending by month",
  top_merchants: "Top merchants",
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export interface FormattedToolCall {
  title: string;
  /** e.g. ["Mar 1, 2024 to Mar 31, 2024", "Top 3"] */
  details: string[];
}

export function formatToolCall(call: ToolCall): FormattedToolCall {
  const title = TOOL_NAMES[call.name] ?? humanize(call.name);
  const args = call.arguments ?? {};
  const details: string[] = [];

  const start = dateText(args.start);
  const end = dateText(args.end);
  if (start && end) details.push(`${start} to ${end}`);
  else if (start) details.push(`From ${start}`);
  else if (end) details.push(`Up to ${end}`);
  else details.push("All time");

  if (args.limit !== undefined) details.push(`Top ${String(args.limit)}`);

  // Anything else the model sent is shown as-is rather than hidden.
  for (const [key, value] of Object.entries(args)) {
    if (key === "start" || key === "end" || key === "limit") continue;
    details.push(`${humanize(key)}: ${typeof value === "string" ? value : JSON.stringify(value)}`);
  }
  return { title, details };
}

function dateText(value: unknown): string | null {
  if (typeof value !== "string" || value === "") return null;
  return ISO_DATE.test(value) ? formatDay(value) : value;
}

function humanize(name: string): string {
  const words = name.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
