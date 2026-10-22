"use client";

import { useMemo, useState } from "react";
import { layoutTrend, nearestPoint, shortDate, type TrendPoint } from "@/lib/stats";

const W = 300;
const H = 90;

interface Props {
  title: string;
  /** One value per practice day; days without a value are left out by the caller. */
  series: TrendPoint[];
  format: (v: number) => string;
  /** Fixed y range (clarity is 0 to 100); otherwise it fits the data. */
  domain?: [number, number];
  /** True when a lower number is the better one (filler rate). */
  lowerIsBetter?: boolean;
}

/** One measure, one line, one colour: small multiples keep each scale honest, no dual axis. */
export function TrendChart({ title, series, format, domain, lowerIsBetter }: Props) {
  const g = useMemo(() => layoutTrend(series, W, H, undefined, domain), [series, domain]);
  const [hover, setHover] = useState<number | null>(null);
  if (series.length === 0) return null;
  const last = g.points[g.points.length - 1];
  const active = hover === null ? null : g.points[hover];
  return (
    <figure className="flex flex-col gap-1" data-testid={`trend-${title.toLowerCase().replace(/\W+/g, "-")}`}>
      <figcaption className="flex items-baseline justify-between text-sm">
        <span className="font-medium">{title}</span>
        <span className="text-xs opacity-60">{lowerIsBetter ? "lower is better" : "higher is better"}</span>
      </figcaption>
      <div className="relative">
        <svg
          role="img"
          aria-label={`${title}. Latest ${format(last.src.value)} on ${shortDate(last.src.date)}.`}
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full touch-none text-indigo-600 dark:text-indigo-400"
          onPointerMove={(e) => {
            const box = e.currentTarget.getBoundingClientRect();
            const near = nearestPoint(g, ((e.clientX - box.left) / box.width) * W);
            setHover(near ? near.index : null);
          }}
          onPointerLeave={() => setHover(null)}
        >
          <line x1={6} x2={W - 44} y1={H - 8} y2={H - 8} className="stroke-neutral-200 dark:stroke-neutral-800" strokeWidth={1} />
          {g.points.length > 1 && (
            <path d={g.line} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          )}
          {active && (
            <circle cx={active.x} cy={active.y} r={4} fill="currentColor" className="stroke-white dark:stroke-neutral-950" strokeWidth={2} />
          )}
          <circle cx={last.x} cy={last.y} r={4} fill="currentColor" className="stroke-white dark:stroke-neutral-950" strokeWidth={2} />
          <text x={last.x + 8} y={last.y + 4} className="fill-neutral-900 text-[12px] font-medium dark:fill-neutral-100">
            {format(last.src.value)}
          </text>
        </svg>
        {active && (
          <div
            data-testid="trend-tooltip"
            style={{ left: `${(active.x / W) * 100}%` }}
            className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-md border border-neutral-200 bg-white px-2 py-1 text-xs shadow dark:border-neutral-700 dark:bg-neutral-900"
          >
            <div className="font-medium">{shortDate(active.src.date)}</div>
            <div>{format(active.src.value)}</div>
          </div>
        )}
      </div>
    </figure>
  );
}
