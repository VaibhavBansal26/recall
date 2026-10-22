"use client";

import { useState } from "react";
import type { LinkItem, NoteCard } from "@/lib/events";

interface Props {
  notes: NoteCard[];
  links: LinkItem[];
  selectedId: string | null;
  onSelect: (noteId: string) => void;
  onUndo: (eventId: string) => Promise<void>;
  onConfirm?: (noteId: string) => Promise<void>;
}

function NoteItem({
  note,
  links,
  selected,
  onSelect,
  onUndo,
  onConfirm,
}: {
  note: NoteCard;
  links: LinkItem[];
  selected: boolean;
  onSelect: () => void;
  onUndo: Props["onUndo"];
  onConfirm?: Props["onConfirm"];
}) {
  const [busy, setBusy] = useState(false);
  const [showBefore, setShowBefore] = useState(false);
  const change = note.change;
  // Rule 6: anything the assistant added looks different until the user confirms it.
  const unconfirmed = !note.confirmed;

  return (
    <li
      className={`rounded-xl border p-3 text-sm ${
        selected ? "ring-2 ring-indigo-500" : ""
      } ${
        unconfirmed
          ? "border-dashed border-amber-500/70 bg-amber-50 dark:bg-amber-950/20"
          : "border-neutral-200 dark:border-neutral-800"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-medium">
          <button type="button" onClick={onSelect} aria-pressed={selected} className="text-left">
            {note.title}
          </button>
        </h3>
        {change && (
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onUndo(change.eventId);
              } finally {
                setBusy(false);
              }
            }}
            className="shrink-0 rounded border border-neutral-300 px-2 py-0.5 text-xs hover:bg-neutral-100 disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            Undo
          </button>
        )}
      </div>
      <p className="mt-1 whitespace-pre-wrap opacity-90">{note.bodyMd}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {change?.action === "created" && (
          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
            New note
          </span>
        )}
        {change?.action === "merged" && (
          <>
            <span className="rounded bg-sky-100 px-1.5 py-0.5 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300">
              Merged into existing note
              {change.similarity !== null && ` (${Math.round(change.similarity * 100)}% match)`}
            </span>
            <button
              type="button"
              onClick={() => setShowBefore((v) => !v)}
              className="underline opacity-70"
            >
              {showBefore ? "Hide previous" : "Show previous"}
            </button>
          </>
        )}
        {unconfirmed && (
          <>
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
              {note.origin === "source" ? "From source, unconfirmed" : "From assistant, unconfirmed"}
            </span>
            {onConfirm && (
              <button
                type="button"
                onClick={() => void onConfirm(note.noteId)}
                className="rounded border border-neutral-300 px-2 py-0.5 dark:border-neutral-700"
              >
                Confirm
              </button>
            )}
          </>
        )}
        {note.fragile && (
          <span
            data-testid="fragile-badge"
            className="rounded bg-red-100 px-1.5 py-0.5 text-red-900 dark:bg-red-900/40 dark:text-red-200"
          >
            ⚠ Fragile
          </span>
        )}
      </div>
      {links.length > 0 && (
        <ul aria-label="Links" className="mt-2 flex flex-col gap-1 text-xs">
          {links.map((l) => {
            const outgoing = l.from_note_id === note.noteId;
            return (
              <li
                key={l.id}
                className={
                  l.confirmed
                    ? "opacity-80"
                    : "rounded border border-dashed border-amber-500/70 px-1.5 py-0.5 text-amber-800 dark:text-amber-300"
                }
              >
                {outgoing ? `${l.kind.replace("_", " ")} → ${l.to_title}` : `${l.from_title} → ${l.kind.replace("_", " ")}`}
                {!l.confirmed && " (unconfirmed)"}
              </li>
            );
          })}
        </ul>
      )}
      {showBefore && change?.beforeBodyMd && (
        <p className="mt-2 whitespace-pre-wrap border-l-2 border-neutral-300 pl-2 opacity-70 dark:border-neutral-700">
          {change.beforeBodyMd}
        </p>
      )}
    </li>
  );
}

export function NotePane({ notes, links, selectedId, onSelect, onUndo, onConfirm }: Props) {
  return (
    <section aria-label="Notes" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">
        Notes <span data-testid="note-count">({notes.length})</span>
      </h2>
      {notes.length === 0 ? (
        <p className="text-sm opacity-60">Notes appear here as you talk.</p>
      ) : (
        <ul className="flex flex-col gap-2" aria-label="Note list">
          {notes.map((n) => (
            <NoteItem
              key={n.noteId}
              note={n}
              links={links.filter((l) => l.from_note_id === n.noteId || l.to_note_id === n.noteId)}
              selected={n.noteId === selectedId}
              onSelect={() => onSelect(n.noteId)}
              onUndo={onUndo}
              onConfirm={onConfirm}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
