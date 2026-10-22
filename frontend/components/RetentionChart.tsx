"use client";

import { useMemo, useState } from "react";
import { layoutCurve, nearestPoint, pct, shortDate, type CurvePoint } from "@/lib/stats";

const W = 640;
const H = 220;

/**
 * Retention by day: the share of that day's reviews you recalled (Hard, Good or Easy).
 * One series, so no legend: the heading names it. Days with no reviews are gaps.
 */
export function RetentionChart({ series }: { series: CurvePoint[] }) {
  const g = useMemo(() => layoutCurve(series, W, H), [series]);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const last = g.points[g.points.length - 1];
  const active = hover !== null ? (g.points.find((p) => p.index === hover) ?? null) : null;

  if (g.points.length === 0) {
    return (
      <p className="text-sm opacity-60">
        No reviews in the last 30 days yet. Take a quiz and the curve appears.
      </p>
    );
  }

  return (
    <figure className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <figcaption className="text-sm font-medium">Retention, last 30 days</figcaption>
        <button
          type="button"
          onClick={() => setTable((t) => !t)}
          aria-pressed={table}
          className="rounded border border-neutral-300 px-2 py-1 text-xs dark:border-neutral-700"
        >
          {table ? "View chart" : "View as table"}
        </button>
      </div>

      {table ? (
        <table className="w-full text-left text-sm" data-testid="retention-table">
          <thead>
            <tr className="opacity-60">
              <th className="py-1 font-normal">Day</th>
              <th className="py-1 font-normal">Reviews</th>
              <th className="py-1 font-normal">Recalled</th>
              <th className="py-1 font-normal">Retention</th>
            </tr>
          </thead>
          <tbody>
            {series
              .filter((s) => s.reviews > 0)
              .map((s) => (
                <tr key={s.date} className="border-t border-neutral-200 dark:border-neutral-800">
                  <td className="py-1">{shortDate(s.date)}</td>
                  <td className="py-1">{s.reviews}</td>
                  <td className="py-1">{s.recalled}</td>
                  <td className="py-1">{pct(s.retention)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : (
        <div className="relative">
          <svg
            role="img"
            aria-label={`Retention by day. Latest ${pct(last.src.retention)} on ${shortDate(last.src.date)}.`}
            viewBox={`0 0 ${W} ${H}`}
            className="h-auto w-full touch-none text-indigo-600 dark:text-indigo-400"
            onPointerMove={(e) => {
              const box = e.currentTarget.getBoundingClientRect();
              const nearest = nearestPoint(g, ((e.clientX - box.left) / box.width) * W);
              setHover(nearest ? nearest.index : null);
            }}
            onPointerLeave={() => setHover(null)}
          >
            {g.yTicks.map((t) => (
              <g key={t.label}>
                <line
                  x1={36}
                  x2={W - 40}
                  y1={t.y}
                  y2={t.y}
                  className="stroke-neutral-200 dark:stroke-neutral-800"
                  strokeWidth={1}
                />
                <text
                  x={30}
                  y={t.y + 4}
                  textAnchor="end"
                  className="fill-neutral-500 text-[11px] dark:fill-neutral-400"
                >
                  {t.label}
                </text>
              </g>
            ))}
            {g.xTicks.map((t) => (
              <text
                key={t.label + t.x}
                x={t.x}
                y={H - 6}
                textAnchor="middle"
                className="fill-neutral-500 text-[11px] dark:fill-neutral-400"
              >
                {t.label}
              </text>
            ))}
            <path d={g.area} fill="currentColor" fillOpacity={0.1} stroke="none" />
            <path
              d={g.line}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {active && (
              <g>
                <line
                  x1={active.x}
                  x2={active.x}
                  y1={12}
                  y2={H - 24}
                  className="stroke-neutral-400"
                  strokeWidth={1}
                />
                <circle
                  cx={active.x}
                  cy={active.y}
                  r={4}
                  fill="currentColor"
                  className="stroke-white dark:stroke-neutral-950"
                  strokeWidth={2}
                />
              </g>
            )}
            {/* The latest value is labelled at the line's end, not on every point. */}
            <circle
              cx={last.x}
              cy={last.y}
              r={4}
              fill="currentColor"
              className="stroke-white dark:stroke-neutral-950"
              strokeWidth={2}
            />
            <text
              x={last.x + 8}
              y={last.y + 4}
              className="fill-neutral-900 text-[12px] font-medium dark:fill-neutral-100"
            >
              {pct(last.src.retention)}
            </text>
          </svg>
          {active && (
            <div
              data-testid="chart-tooltip"
              style={{ left: `${(active.x / W) * 100}%` }}
              className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-md border border-neutral-200 bg-white px-2 py-1 text-xs shadow dark:border-neutral-700 dark:bg-neutral-900"
            >
              <div className="font-medium">{shortDate(active.src.date)}</div>
              <div>
                {active.src.recalled} of {active.src.reviews} recalled · {pct(active.src.retention)}
              </div>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
