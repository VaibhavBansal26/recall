"use client";

import { useState } from "react";
import { saveAssistantNote } from "@/lib/api";
import type { Explanation } from "@/lib/events";
import { DiagramView } from "./DiagramView";

interface Props {
  explanation: Explanation;
  track: string;
  onSaved: () => void;
}

export function ExplainCard({ explanation, track, onSaved }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await saveAssistantNote(track, explanation.topic, explanation.text);
      onSaved();
    } catch {
      setError("Could not save the note.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Explanation"
      data-testid="explain-card"
      className="flex flex-col gap-2 rounded-xl border border-dashed border-amber-500/70 bg-amber-50 p-4 text-sm dark:bg-amber-950/20"
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="font-semibold">
          {explanation.simple ? "Simpler: " : ""}
          {explanation.topic}
        </h2>
        <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
          From assistant
        </span>
      </div>
      <p className="whitespace-pre-wrap opacity-90">{explanation.text}</p>
      {explanation.diagram && <DiagramView diagram={explanation.diagram} />}
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={busy || explanation.saved}
          onClick={() => void save()}
          className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm disabled:opacity-50 dark:border-neutral-700"
        >
          {explanation.saved ? "Saved as unconfirmed note" : "Save as note"}
        </button>
        {error && (
          <span role="alert" className="text-red-600 dark:text-red-400">
            {error}
          </span>
        )}
      </div>
      <p className="text-xs opacity-60">
        Not in your notes until you save it, and it stays marked as the assistant&apos;s until you
        confirm it.
      </p>
    </section>
  );
}
