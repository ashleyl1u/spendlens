import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { askErrorMessage, MAX_QUESTION } from "./ask";
import { formatToolCall } from "./toolCalls";

describe("formatToolCall", () => {
  it("names the tool and reads a date range", () => {
    expect(
      formatToolCall({
        name: "spending_by_category",
        arguments: { start: "2024-03-01", end: "2024-03-31" },
      }),
    ).toEqual({ title: "Spending by category", details: ["Mar 1, 2024 to Mar 31, 2024"] });
  });

  it("says All time when there are no dates", () => {
    expect(formatToolCall({ name: "spending_summary", arguments: {} })).toEqual({
      title: "Spending summary",
      details: ["All time"],
    });
  });

  it("shows one-sided ranges and the limit", () => {
    expect(formatToolCall({ name: "top_merchants", arguments: { start: "2024-04-01", limit: 3 } })).toEqual({
      title: "Top merchants",
      details: ["From Apr 1, 2024", "Top 3"],
    });
    expect(formatToolCall({ name: "spending_by_month", arguments: { end: "2024-12-31" } }).details).toEqual([
      "Up to Dec 31, 2024",
    ]);
  });

  it("shows unexpected arguments and tools instead of hiding them", () => {
    expect(
      formatToolCall({ name: "delete_everything", arguments: { start: "last month", user_id: 7 } }),
    ).toEqual({ title: "Delete everything", details: ["From last month", "User id: 7"] });
  });
});

describe("askErrorMessage", () => {
  it("explains a 503 plainly", () => {
    expect(askErrorMessage(new ApiError(503, "The assistant is unavailable"))).toBe(
      "The assistant is unavailable right now. Please try again in a minute.",
    );
  });

  it("explains a 422", () => {
    expect(askErrorMessage(new ApiError(422, "question: too long"))).toBe(
      `Questions can be up to ${MAX_QUESTION} characters and can't be blank.`,
    );
  });

  it("passes other errors through", () => {
    expect(askErrorMessage(new ApiError(0, "Can't reach the spendlens server."))).toBe(
      "Can't reach the spendlens server.",
    );
  });
});
