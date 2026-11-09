/**
 * Dashboard charts. Each is a single series, so each uses one color (--series-1,
 * validated for contrast against the chart surface in light and dark mode). Category
 * and month names are axis text, and every value is also shown as text in the table
 * next to the chart, so nothing depends on color alone.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TooltipProps } from "recharts";

import { formatMonth } from "../lib/dates";
import { formatCents } from "../lib/money";
import { formatShare } from "../lib/percent";
import type { CategoryTotal, MonthTotal } from "../lib/types";

const TICK = { fill: "var(--text-secondary)", fontSize: 12 };

// Recharts animates in JavaScript, so the CSS reduced-motion rule can't stop it.
const animate =
  typeof window === "undefined" ||
  !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Bars start at zero, or below it when refunds make a total negative. The top is left to
 * Recharts ("auto") so it rounds up to an even tick ($0, $50, $100, ... $250) instead of
 * ending on the exact largest value.
 */
const fromZero: [(min: number) => number, "auto"] = [(min) => Math.min(0, min), "auto"];

function ChartTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload as Partial<CategoryTotal & MonthTotal>;
  return (
    <div className="chart-tooltip">
      <p className="chart-tooltip-title">
        {row.category ?? (row.month ? formatMonth(row.month, "long") : "")}
      </p>
      <p>{formatCents(row.total_cents ?? 0)}</p>
      <p className="chart-tooltip-meta">
        {row.transaction_count} transaction{row.transaction_count === 1 ? "" : "s"}
        {row.share !== undefined && ` · ${formatShare(row.share)} of spending`}
      </p>
    </div>
  );
}

export function CategoryChart({ data }: { data: CategoryTotal[] }) {
  const height = Math.max(120, data.length * 36 + 40);
  const summary = data
    .slice(0, 3)
    .map((c) => `${c.category} ${formatCents(c.total_cents)}`)
    .join(", ");
  return (
    <figure className="chart">
      <figcaption className="visually-hidden">
        Bar chart of spending by category, largest first: {summary}. Every value is in the
        table.
      </figcaption>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
          barCategoryGap={8}
          // No accessibilityLayer: Recharts 2 can't move through a horizontal-bar chart
          // with the arrow keys, so it would be a dead tab stop. Keyboard and screen
          // reader users get every value from the table beside the chart instead.
        >
          <CartesianGrid horizontal={false} stroke="var(--grid)" />
          <XAxis
            type="number"
            domain={fromZero}
            tickFormatter={(cents: number) => formatCents(cents, { compact: true })}
            tick={TICK}
            axisLine={{ stroke: "var(--axis)" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="category"
            width={118}
            tick={TICK}
            axisLine={{ stroke: "var(--axis)" }}
            tickLine={false}
            interval={0}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--hover-wash)" }} />
          <Bar dataKey="total_cents" name="Spent" fill="var(--series-1)" isAnimationActive={animate} radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}

export function MonthlyChart({ data }: { data: MonthTotal[] }) {
  const peak = data.reduce((best, m) => (m.total_cents > best.total_cents ? m : best), data[0]);
  return (
    <figure className="chart">
      <figcaption className="visually-hidden">
        Bar chart of spending per month from {formatMonth(data[0].month, "long")} to{" "}
        {formatMonth(data[data.length - 1].month, "long")}. Highest:{" "}
        {formatMonth(peak.month, "long")}, {formatCents(peak.total_cents)}. Every value is in
        the table below.
      </figcaption>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 4 }} accessibilityLayer>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="month"
            tickFormatter={(month: string) => formatMonth(month)}
            tick={TICK}
            axisLine={{ stroke: "var(--axis)" }}
            tickLine={false}
            minTickGap={12}
          />
          <YAxis
            domain={fromZero}
            tickFormatter={(cents: number) => formatCents(cents, { compact: true })}
            tick={TICK}
            axisLine={false}
            tickLine={false}
            width={64}
          />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--hover-wash)" }} />
          <Bar dataKey="total_cents" name="Spent" fill="var(--series-1)" isAnimationActive={animate} radius={[4, 4, 0, 0]} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}
