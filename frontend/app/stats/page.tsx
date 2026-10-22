"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RetentionChart } from "@/components/RetentionChart";
import { getStats, type StatsOut } from "@/lib/api";
import { pct } from "@/lib/stats";
import { useRefreshOnFocus } from "@/lib/useRefreshOnFocus";

function Tile({
  label,
  value,
  hint,
  testid,
}: {
  label: string;
  value: string;
  hint?: string;
  testid?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <span className="text-xs opacity-60">{label}</span>
      <span data-testid={testid} className="text-2xl font-semibold">
        {value}
      </span>
      {hint && <span className="text-xs opacity-60">{hint}</span>}
    </div>
  );
}

function StrengthMeter({ value, fragile }: { value: number | null; fragile: boolean }) {
  const width = value === null ? 0 : Math.max(4, Math.round(value * 100));
  return (
    <div
      role="meter"
      aria-label="Memory strength"
      aria-valuenow={value === null ? undefined : Math.round(value * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      className="h-2 w-24 overflow-hidden rounded-full bg-indigo-100 dark:bg-indigo-950"
    >
      <div
        className={`h-full rounded-full ${fragile ? "bg-red-500" : "bg-indigo-600 dark:bg-indigo-400"}`}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

export default function StatsPage() {
  const [stats, setStats] = useState<StatsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStats(await getStats("ai-eng"));
      setError(null);
    } catch {
      setError("Could not load your stats.");
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useRefreshOnFocus(refresh);

  if (error) {
    return (
      <main className="mx-auto max-w-5xl p-6">
        <p role="alert" className="text-red-600 dark:text-red-400">
          {error}
        </p>
      </main>
    );
  }
  if (!stats) return <main className="mx-auto max-w-5xl p-6 text-sm opacity-60">Loading…</main>;

  const streakHint =
    stats.streak_current === 0
      ? "Review once today to start one"
      : stats.reviewed_today
        ? `Longest ${stats.streak_longest}`
        : `Review today to keep it · longest ${stats.streak_longest}`;
  const articulation = stats.articulation_trend ?? [];

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Stats</h1>
          <p className="text-sm opacity-70">
            {stats.notes_total} notes · {stats.items_reviewed} of {stats.items_total} questions
            reviewed
            {stats.fragile_notes > 0 ? ` · ${stats.fragile_notes} fragile` : ""}
          </p>
        </div>
        <Link href="/review" className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white">
          Start reviewing
        </Link>
      </header>

      <section aria-label="Due today" className="flex flex-col gap-1">
        <span className="text-xs opacity-60">Due today</span>
        <span data-testid="due-today" className="text-5xl font-semibold">
          {stats.due_today}
        </span>
        <span className="text-sm opacity-70">{stats.due_now} due right now</span>
      </section>

      <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile
          label="Streak"
          value={`${stats.streak_current} day${stats.streak_current === 1 ? "" : "s"}`}
          hint={streakHint}
          testid="streak"
        />
        <Tile
          label="Retention, 7 days"
          value={pct(stats.retention_7d)}
          hint="Hard, Good or Easy"
          testid="retention-7d"
        />
        <Tile label="Retention, 30 days" value={pct(stats.retention_30d)} testid="retention-30d" />
        <Tile label="Without a hint" value={pct(stats.unaided_rate_30d)} hint="Last 30 days" />
      </section>

      <section className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
        <RetentionChart series={stats.retention_curve} />
      </section>

      <section aria-label="Weakest notes" className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Weakest notes</h2>
        {stats.weak_nodes.length === 0 ? (
          <p className="text-sm opacity-60">
            Nothing is slipping yet. Once you have reviewed some notes, the weakest show here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {stats.weak_nodes.map((w) => (
              <li
                key={w.note_id}
                data-testid="weak-note"
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-neutral-200 p-3 text-sm dark:border-neutral-800"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">
                    {w.fragile ? (
                      <span title="Fragile" aria-label="Fragile">
                        ⚠{" "}
                      </span>
                    ) : null}
                    {w.title}
                  </p>
                  <p className="text-xs opacity-60">
                    {pct(w.strength)} remembered
                    {w.lapses ? ` · ${w.lapses} recent miss${w.lapses === 1 ? "" : "es"}` : ""}
                  </p>
                </div>
                <StrengthMeter value={w.strength ?? null} fragile={w.fragile ?? false} />
                <Link
                  href={`/review?note=${w.note_id}`}
                  className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700"
                >
                  Quiz me
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        aria-label="Articulation"
        className="rounded-xl border border-dashed border-neutral-300 p-4 text-sm dark:border-neutral-700"
      >
        <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">
          Articulation trend
        </h2>
        <p className="mt-1 opacity-70">
          {articulation.length === 0
            ? "Appears once you practise explaining out loud in the English track."
            : `${articulation.length} teach-back sessions recorded.`}
        </p>
      </section>
    </main>
  );
}
