"use client";

import { useState } from "react";
import { regenerateDiagram } from "@/lib/api";
import type { DiagramItem, NoteCard } from "@/lib/events";
import { DiagramView } from "./DiagramView";

interface Props {
  note: NoteCard | null;
  diagram: DiagramItem | null;
  onDiagram: (d: DiagramItem) => void;
}

export function DiagramPane({ note, diagram, onDiagram }: Props) {
  const [busy, setBusy] = useState(false);
  return (
    <section aria-label="Diagram" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Diagram</h2>
        {note && (
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                onDiagram(await regenerateDiagram(note.noteId));
              } finally {
                setBusy(false);
              }
            }}
            className="rounded border border-neutral-300 px-2 py-0.5 text-xs disabled:opacity-40 dark:border-neutral-700"
          >
            {busy ? "Redrawing…" : "Redraw"}
          </button>
        )}
      </div>
      {!note ? (
        <p className="text-sm opacity-60">Pick a note to see its diagram.</p>
      ) : (
        <>
          <p className="text-sm font-medium">{note.title}</p>
          {diagram ? (
            <DiagramView diagram={diagram} />
          ) : (
            <p className="text-sm opacity-60">Drawing a diagram for this note…</p>
          )}
        </>
      )}
    </section>
  );
}
