const percent = new Intl.NumberFormat("en-CA", {
  style: "percent",
  // Always one decimal, so a column reads 29.7%, 14.0%, 3.6% rather than mixing 14% in.
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/** A share of a total (0.296) as a percentage ("29.6%"). */
export function formatShare(share: number): string {
  return percent.format(share);
}
