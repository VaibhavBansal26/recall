"use client";

import { useState } from "react";
import type { BeatName, TeachBackView } from "@/lib/events";

const BEATS: { key: BeatName; label: string }[] = [
  { key: "what", label: "What" },
  { key: "how", label: "How" },
  { key: "why", label: "Why" },
  { key: "impact", label: "Impact" },
];

function Tile({ label, value, hint, testid }: { label: string; value: string; hint?: string; testid: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
      <span className="text-xs opacity-60">{label}</span>
      <span data-testid={testid} className="text-xl font-semibold">
        {value}
      </span>
      {hint && <span className="text-xs opacity-60">{hint}</span>}
    </div>
  );
}

const num = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "–" : v.toFixed(digits);

interface Props {
  view: TeachBackView | null;
  ready: boolean;
  onStart: (topic: string | null) => void;
  onDone: () => void;
  onCancel: () => void;
  onClose: () => void;
}

export function TeachBackPanel({ view, ready, onStart, onDone, onCancel, onClose }: Props) {
  const [topic, setTopic] = useState("");
  const phase = view?.phase;

  if (!view || phase === "too_short") {
    return (
      <section aria-label="Teach-back" className="flex flex-col gap-3 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
        <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Teach-back</h2>
        {phase === "too_short" ? (
          <p role="status" data-testid="teachback-too-short" className="text-sm">
            That was too short to score ({view?.words} words). Try explaining it in a few sentences.
          </p>
        ) : (
          <p className="text-sm opacity-70">
            Explain an idea out loud. You get speaking metrics and feedback on what, how, why and impact.
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onStart(topic.trim() || null);
            setTopic("");
          }}
          className="flex gap-2"
        >
          <input
            aria-label="Teach-back topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Topic, or leave empty for a suggestion"
            className="min-h-11 flex-1 rounded-lg border border-neutral-300 bg-transparent px-3 py-2 text-base dark:border-neutral-700"
          />
          <button
            type="submit"
            disabled={!ready}
            className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white disabled:opacity-40"
          >
            Start
          </button>
        </form>
      </section>
    );
  }

  if (phase === "listening" || phase === "scoring") {
    return (
      <section aria-label="Teach-back" className="flex flex-col gap-3 rounded-xl border border-indigo-300 p-4 dark:border-indigo-800">
        <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Teach-back</h2>
        <p className="text-lg font-medium" data-testid="teachback-topic">
          {view.topic || "Explain it in your own words"}
        </p>
        {phase === "scoring" ? (
          <p role="status" className="text-sm opacity-70">
            Scoring your explanation…
          </p>
        ) : (
          <>
            <p role="status" aria-live="polite" className="text-sm opacity-70">
              Listening. <span data-testid="teachback-words">{view.words}</span> words so far. Say
              “I’m done” when you finish.
            </p>
            {view.ideas.length > 0 && (
              <p className="text-xs opacity-60">Other ideas: {view.ideas.join(" · ")}</p>
            )}
            <div className="flex gap-2">
              <button type="button" onClick={onDone} className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white">
                I’m done
              </button>
              <button
                type="button"
                onClick={onCancel}
                className="min-h-11 rounded-lg border border-neutral-300 px-4 py-2 dark:border-neutral-700"
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </section>
    );
  }

  const m = view.metrics;
  return (
    <section aria-label="Teach-back result" data-testid="teachback-result" className="flex flex-col gap-4 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Teach-back</h2>
          <p className="font-medium">{view.topic}</p>
        </div>
        <button type="button" onClick={onClose} className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700">
          Try another
        </button>
      </div>

      {m && (
        <div className="grid grid-cols-2 gap-2">
          <Tile label="Pace" value={m.wpm === null ? "–" : `${num(m.wpm)} wpm`} hint={m.wpm === null ? "Needs spoken audio" : "Calm is 120 to 160"} testid="metric-wpm" />
          <Tile label="Fillers" value={`${num(m.filler_rate, 1)} per 100`} hint={`${m.filler_count} in ${m.word_count} words`} testid="metric-fillers" />
          <Tile label="Long pauses" value={String(m.long_pauses)} hint={m.long_pauses ? `Longest ${num(m.longest_pause_s, 1)} s` : "None over 1.5 s"} testid="metric-pauses" />
          <Tile label="Sentence length" value={`${num(m.sentences.mean, 1)} words`} hint={m.sentences.punctuated ? `Longest ${m.sentences.longest}` : "No sentence breaks found"} testid="metric-sentences" />
        </div>
      )}

      {view.beats && (
        <div>
          <div className="mb-1 flex items-baseline justify-between text-sm">
            <h3 className="font-medium">Structure</h3>
            <span data-testid="structure-score">{num(view.structure)} / 100</span>
          </div>
          <ul className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            {BEATS.map(({ key, label }) => {
              const beat = view.beats?.[key];
              return (
                <li
                  key={key}
                  data-testid={`beat-${key}`}
                  data-present={beat?.present ?? false}
                  title={beat?.evidence || undefined}
                  className="rounded-lg border border-neutral-200 px-2 py-1 dark:border-neutral-800"
                >
                  <span aria-hidden="true">{beat?.present ? "✓" : "✗"} </span>
                  {label}
                  <span className="sr-only">{beat?.present ? " present" : " missing"}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="text-sm">
        <div className="flex items-baseline justify-between">
          <h3 className="font-medium">Clarity</h3>
          <span data-testid="clarity-score">{num(view.clarity)} / 100</span>
        </div>
        {view.clarityReason && <p className="opacity-70">{view.clarityReason}</p>}
      </div>

      {(view.wellDone || view.toFix) && (
        <div className="flex flex-col gap-1 text-sm">
          {view.wellDone && (
            <p>
              <strong>Done well:</strong> {view.wellDone}
            </p>
          )}
          {view.toFix && (
            <p>
              <strong>To fix:</strong> {view.toFix}
            </p>
          )}
        </div>
      )}

      {view.suggestions.length > 0 && (
        <ul className="list-disc pl-5 text-sm">
          {view.suggestions.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      )}

      {view.rewrite && (
        <div className="grid gap-2 text-sm md:grid-cols-2" data-testid="rewrite">
          <blockquote className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
            <span className="mb-1 block text-xs opacity-60">You said</span>
            {view.rewrite.original}
          </blockquote>
          <blockquote className="rounded-lg border border-emerald-300 p-3 dark:border-emerald-800">
            <span className="mb-1 block text-xs opacity-60">Try</span>
            {view.rewrite.improved}
          </blockquote>
        </div>
      )}
    </section>
  );
}
