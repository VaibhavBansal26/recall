"use client";

import { useState } from "react";
import {
  ACTIVE_STATUSES,
  approveSource,
  chooseSourceTrack,
  getSourceDetail,
  retrySource,
  undoCapture,
  type SourceDetail,
  type SourceOut,
  type TrackOut,
} from "@/lib/api";
import { describeProgress, shortUri } from "@/lib/sources";

interface Props {
  source: SourceOut;
  tracks: TrackOut[];
  onChanged: () => void;
}

const BADGE: Record<string, string> = {
  ready: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  approved: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200",
  failed: "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-200",
  needs_track: "bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-200",
};

export function SourceCard({ source, tracks, onChanged }: Props) {
  const [open, setOpen] = useState(source.status === "ready");
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [choice, setChoice] = useState(source.suggested_track ?? tracks[0]?.slug ?? "");
  const active = ACTIVE_STATUSES.includes(source.status);

  async function load() {
    try {
      setDetail(await getSourceDetail(source.id));
    } catch {
      /* the list will show the error state */
    }
  }

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !detail) await load();
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      onChanged();
      if (open) await load();
    } finally {
      setBusy(false);
    }
  }

  // Keep the expanded details fresh as the source moves from processing to ready.
  const stale = open && (!detail || detail.status !== source.status);
  if (stale && !busy) void load();

  return (
    <li
      data-testid="source-card"
      data-status={source.status}
      className="flex flex-col gap-2 rounded-xl border border-neutral-200 p-4 text-sm dark:border-neutral-800"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-medium">{source.title ?? shortUri(source.uri)}</h3>
          <p className="truncate text-xs opacity-60">
            {source.kind} · {shortUri(source.uri)}
          </p>
        </div>
        <span
          data-testid="source-status"
          className={`shrink-0 rounded px-2 py-0.5 text-xs ${BADGE[source.status] ?? "bg-neutral-100 dark:bg-neutral-800"}`}
        >
          {describeProgress(source.status, source.stage ?? null)}
          {active ? "…" : ""}
        </span>
      </div>

      {source.headline && <p data-testid="source-headline">{source.headline}</p>}
      {source.track_name && (
        <p className="text-xs opacity-70">
          Track: {source.track_name}
          {source.topic ? ` · ${source.topic}` : ""}
        </p>
      )}

      {source.status === "failed" && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" className="text-red-600 dark:text-red-400">
            {source.error}
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void act(() => retrySource(source.id))}
            className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700"
          >
            Retry
          </button>
        </div>
      )}

      {source.status === "needs_track" && (
        <div className="flex flex-wrap items-center gap-2">
          <p>
            I&apos;m not sure which track this belongs to
            {source.track_confidence !== null && source.track_confidence !== undefined
              ? ` (best guess ${Math.round(source.track_confidence * 100)}% sure)`
              : ""}
            .
          </p>
          <select
            aria-label="Track for this source"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            className="min-h-11 rounded-lg border border-neutral-300 bg-transparent px-2 dark:border-neutral-700"
          >
            {tracks.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={busy || !choice}
            onClick={() => void act(() => chooseSourceTrack(source.id, choice))}
            className="min-h-11 rounded-lg bg-indigo-600 px-3 py-2 text-white disabled:opacity-40"
          >
            File it here
          </button>
        </div>
      )}

      {(source.status === "ready" || source.status === "approved") && (
        <div className="flex flex-wrap items-center gap-2">
          {source.status === "ready" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void act(() => approveSource(source.id))}
              className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white disabled:opacity-40"
            >
              Approve all
            </button>
          )}
          <button
            type="button"
            onClick={() => void toggle()}
            aria-expanded={open}
            className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700"
          >
            {open ? "Hide notes" : "Review notes"}
          </button>
        </div>
      )}

      {open && detail && (
        <ul aria-label="Filed notes" className="mt-1 flex flex-col gap-2">
          {(detail.items ?? []).length === 0 && <li className="opacity-60">No notes were filed.</li>}
          {(detail.items ?? []).map((item) => (
            <li
              key={item.event_id}
              data-testid="source-item"
              className={`rounded-lg border p-3 ${
                item.confirmed
                  ? "border-neutral-200 dark:border-neutral-800"
                  : "border-dashed border-amber-500/70 bg-amber-50 dark:bg-amber-950/20"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium">{item.title}</p>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void act(() => undoCapture(item.event_id))}
                  className="shrink-0 rounded border border-neutral-300 px-2 py-0.5 text-xs dark:border-neutral-700"
                >
                  Undo
                </button>
              </div>
              <p className="mt-1 whitespace-pre-wrap opacity-90">{item.body_md}</p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <span
                  className={`rounded px-1.5 py-0.5 ${
                    item.action === "merged"
                      ? "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300"
                      : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                  }`}
                >
                  {item.action === "merged" ? "Merged into existing note" : "New note"}
                </span>
                {!item.confirmed && (
                  <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
                    From source, unconfirmed
                  </span>
                )}
              </div>
              {(item.citations ?? []).map((c, i) => (
                <blockquote
                  key={i}
                  data-testid="citation"
                  className="mt-2 border-l-2 border-neutral-300 pl-2 text-xs opacity-80 dark:border-neutral-700"
                >
                  “{c.quote}” <span className="opacity-60">chunk {c.chunk_idx}</span>
                </blockquote>
              ))}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
