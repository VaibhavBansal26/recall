"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  deleteNotebook,
  listNotebookNotes,
  listNotebooks,
  moveNote,
  renameNotebook,
  type NotebookOut,
} from "@/lib/api";
import type { NoteCard } from "@/lib/events";
import { useTrack } from "@/lib/track";
import { useRefreshOnFocus } from "@/lib/useRefreshOnFocus";

const KIND = { notes: "Notes", discussion: "Discussion", source: "From a source" } as const;

function Notebook({ book, onChanged }: { book: NotebookOut; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState<NoteCard[] | null>(null);
  const [name, setName] = useState(book.name);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) listNotebookNotes(book.id).then(setNotes).catch(() => setNotes([]));
  }, [open, book.id, book.note_count]);

  async function rename() {
    if (!name.trim() || name.trim() === book.name) return;
    try {
      await renameNotebook(book.id, name.trim());
      setError(null);
      onChanged();
    } catch {
      setError("Another notebook in this track already has that name.");
    }
  }

  return (
    <li data-testid="notebook" className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="min-h-11 text-left"
        >
          <span className="font-medium">{book.name}</span>
          <span className="ml-2 text-xs opacity-60">
            {book.note_count} note{book.note_count === 1 ? "" : "s"} · {KIND[book.kind]}
          </span>
        </button>
        <div className="flex gap-2">
          <Link
            href={`/session?notebook=${book.id}`}
            className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700"
          >
            Add notes
          </Link>
          <Link
            href={`/session?recite=${book.id}`}
            className="min-h-11 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white"
          >
            Recite
          </Link>
        </div>
      </div>

      {open && (
        <div className="mt-3 flex flex-col gap-3">
          <ul className="flex flex-col gap-2">
            {(notes ?? []).map((n) => (
              <li key={n.noteId} className="rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-800">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium">
                    {!n.confirmed && <span title="Added by the assistant, not confirmed yet">✦ </span>}
                    {n.title}
                  </p>
                  <button
                    type="button"
                    onClick={() => void moveNote(n.noteId, null).then(onChanged)}
                    className="min-h-9 shrink-0 text-xs underline opacity-70"
                  >
                    Remove from notebook
                  </button>
                </div>
                <p className="opacity-80">{n.bodyMd}</p>
              </li>
            ))}
            {notes?.length === 0 && <li className="text-sm opacity-60">No notes in this notebook yet.</li>}
          </ul>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="Notebook name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => void rename()}
              className="min-h-11 flex-1 rounded-lg border border-neutral-300 bg-transparent px-3 py-2 dark:border-neutral-700"
            />
            <button
              type="button"
              onClick={() => {
                if (window.confirm(`Delete the notebook "${book.name}"? Its notes are kept.`)) {
                  void deleteNotebook(book.id).then(onChanged);
                }
              }}
              className="min-h-11 rounded-lg border border-red-400 px-3 py-2 text-sm text-red-700 dark:text-red-300"
            >
              Delete notebook
            </button>
          </div>
          {error && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export default function NotebooksPage() {
  const track = useTrack((t) => t.track);
  const [books, setBooks] = useState<NotebookOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setBooks(await listNotebooks(track));
      setError(null);
    } catch {
      setError("Could not load your notebooks.");
    }
  }, [track]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useRefreshOnFocus(refresh);

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header>
        <h1 className="text-xl font-semibold">Notebooks</h1>
        <p className="text-sm opacity-70">
          Named files of notes in this track. Say “create a new notes file for binary search” on the
          Session page, or make one there. Recite explains each note and asks you questions in between.
        </p>
      </header>
      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {books && books.length === 0 && (
        <p className="text-sm opacity-60">
          No notebooks in this track yet. Open the <Link href="/session" className="underline">Session</Link>{" "}
          page and create one.
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {books?.map((b) => <Notebook key={b.id} book={b} onChanged={() => void refresh()} />)}
      </ul>
    </main>
  );
}
