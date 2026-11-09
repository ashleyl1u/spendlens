/**
 * Date display. The API sends plain calendar dates ("2024-03-04") and months
 * ("2024-03"); they are formatted in UTC so a time zone can never shift them a day.
 */

const dayFormat = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

const monthFormat = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "short",
  timeZone: "UTC",
});

const monthLongFormat = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "long",
  timeZone: "UTC",
});

export function formatDay(isoDate: string): string {
  return dayFormat.format(new Date(`${isoDate}T00:00:00Z`));
}

export function formatMonth(yearMonth: string, style: "short" | "long" = "short"): string {
  const date = new Date(`${yearMonth}-01T00:00:00Z`);
  return (style === "long" ? monthLongFormat : monthFormat).format(date);
}
