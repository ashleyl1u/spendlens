import { describe, expect, it } from "vitest";

import { formatCents } from "./money";

describe("formatCents", () => {
  it.each([
    [0, "$0.00"],
    [5, "$0.05"],
    [312, "$3.12"],
    [39306, "$393.06"],
    [123456, "$1,234.56"],
    [100000000, "$1,000,000.00"],
  ])("formats %i cents as %s", (cents, expected) => {
    expect(formatCents(cents)).toBe(expected);
  });

  it("shows refunds and credits as negative dollars", () => {
    expect(formatCents(-4520)).toBe("-$45.20");
    expect(formatCents(-15000)).toBe("-$150.00");
  });

  it("never shows negative zero", () => {
    expect(formatCents(-0)).toBe("$0.00");
    expect(formatCents(-0.4)).toBe("$0.00");
  });

  it("rounds stray fractions of a cent instead of showing them", () => {
    expect(formatCents(312.4)).toBe("$3.12");
    expect(formatCents(312.6)).toBe("$3.13");
  });

  it("has a compact form for chart axes", () => {
    expect(formatCents(0, { compact: true })).toBe("$0");
    expect(formatCents(150000, { compact: true })).toBe("$1.5K");
    expect(formatCents(250000000, { compact: true })).toBe("$2.5M");
    expect(formatCents(-500000, { compact: true })).toBe("-$5K");
  });

  it("rejects values that are not numbers of cents", () => {
    expect(() => formatCents(Number.NaN)).toThrow(TypeError);
    expect(() => formatCents(Number.POSITIVE_INFINITY)).toThrow(TypeError);
  });
});
