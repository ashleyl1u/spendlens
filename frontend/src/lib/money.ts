/**
 * The one place money is formatted. The API sends integer cents everywhere (spending is
 * positive, refunds negative); this turns them into Canadian dollars for display.
 */

const full = new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD" });

const compact = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  notation: "compact",
  minimumFractionDigits: 0, // "$5K" on an axis, not "$5.0K"
  maximumFractionDigits: 1,
});

export interface MoneyOptions {
  /** Short form for chart axes: $1.2K instead of $1,234.56. */
  compact?: boolean;
}

export function formatCents(cents: number, options: MoneyOptions = {}): string {
  if (!Number.isFinite(cents)) {
    throw new TypeError(`formatCents expects a number of cents, got ${cents}`);
  }
  // The API only sends whole cents; round anyway so float noise never shows up.
  const dollars = Math.round(cents) / 100;
  // Avoid "-$0.00" for amounts that round to zero.
  const value = Object.is(dollars, -0) ? 0 : dollars;
  return (options.compact ? compact : full).format(value);
}
