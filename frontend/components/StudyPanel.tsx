"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ACTIVE_STATUSES,
  createNotebook,
  getSourceDetail,
  listNotebooks,
  uploadPdf,
  type NotebookOut,
} from "@/lib/api";
import type { ActiveNotebook } from "@/lib/events";

interface Props {
  track: string;
  mode: string;
  active: ActiveNotebook | null;
  ready: boolean;
  onOpen: (notebookId: string | null) => void;
  onRecite: (notebookId: string | null) => void;
  onDiscuss: (topic: string) => void;
  /** Say something as if spoken (used to hand a finished upload to the assistant). */
  onSay: (text: string) => void;
}

const KIND_LABEL = { notes: "Notes", discussion: "Discussion", source: "From a source" } as const;

const btn =
  "min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm disabled:opacity-40 dark:border-neutral-700";
const field =
  "min-h-11 flex-1 rounded-lg border border-neutral-300 bg-transparent px-3 py-2 text-base dark:border-neutral-700";

/** Notebooks (named files of notes in a track), reciting, discussions and uploads in one place. */
export function StudyPanel({ track, mode, active, ready, onOpen, onRecite, onDiscuss, onSay }: Props) {
  const [books, setBooks] = useState<NotebookOut[]>([]);
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const [upload, setUpload] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Reload the list when the track changes or the open notebook changes (a new one was made).
  const activeId = active?.id ?? null;
  const activeCount = active?.noteCount ?? 0;
  useEffect(() => {
    let cancelled = false;
    listNotebooks(track)
      .then((b) => !cancelled && setBooks(b))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [track, activeId, activeCount, mode]);

  async function create(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setError(null);
    try {
      const book = await createNotebook(track, trimmed);
      setName("");
      setBooks((prev) => (prev.some((b) => b.id === book.id) ? prev : [book, ...prev]));
      onOpen(book.id);
    } catch {
      setError("Could not create that notebook.");
    }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    setUpload(`Uploading ${file.name}…`);
    const res = await uploadPdf(file, null);
    if (!res.ok) {
      setUpload(null);
      setError(res.error);
      return;
    }
    // Wait for it to be read and filed (usually under a minute), then hand it to the assistant.
    let source = res.source;
    for (let i = 0; i < 90 && ACTIVE_STATUSES.includes(source.status); i++) {
      setUpload(`Reading ${source.title ?? file.name}… ${source.stage ?? ""}`.trim());
      await new Promise((r) => setTimeout(r, 2000));
      source = await getSourceDetail(source.id);
    }
    if (source.status === "ready") {
      setUpload(`${source.title ?? file.name} is ready.`);
      onSay("review the new material");
    } else if (source.status === "failed") {
      setUpload(null);
      setError(source.error ?? "That file could not be read.");
    } else {
      setUpload(`${source.title ?? file.name}: ${source.status}`);
    }
    if (fileInput.current) fileInput.current.value = "";
  }

  return (
    <section
      aria-label="Study"
      className="flex flex-col gap-3 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Notebooks</h2>

      <p data-testid="active-notebook" className="text-sm">
        {active ? (
          <>
            Filing into <strong>{active.name}</strong> · {active.noteCount} note
            {active.noteCount === 1 ? "" : "s"} · {KIND_LABEL[active.kind]}
          </>
        ) : (
          <span className="opacity-70">
            No notebook open. Say “create a new notes file for binary search” or pick one below.
          </span>
        )}
        {mode === "discuss" && (
          <span className="ml-2 rounded-full bg-indigo-600 px-2 py-0.5 text-xs text-white">
            Discussing
          </span>
        )}
      </p>

      <div className="flex flex-wrap gap-2">
        <select
          aria-label="Open notebook"
          value={activeId ?? ""}
          disabled={!ready}
          onChange={(e) => onOpen(e.target.value || null)}
          className={`${field} max-w-full`}
        >
          <option value="">No notebook</option>
          {books.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name} ({b.note_count})
            </option>
          ))}
        </select>
        <button type="button" disabled={!ready || !activeId} onClick={() => onRecite(activeId)} className={btn}>
          Recite with questions
        </button>
      </div>

      <form onSubmit={create} className="flex gap-2">
        <input
          aria-label="New notebook name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New notes file, e.g. Binary search"
          className={field}
        />
        <button type="submit" disabled={!ready || !name.trim()} className={btn}>
          Create
        </button>
      </form>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (topic.trim()) {
            onDiscuss(topic.trim());
            setTopic("");
          }
        }}
        className="flex gap-2"
      >
        <input
          aria-label="Discussion topic"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Discuss a problem, e.g. design a URL shortener"
          className={field}
        />
        <button type="submit" disabled={!ready || !topic.trim()} className={btn}>
          Discuss
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf"
          aria-label="Upload a PDF"
          disabled={!ready}
          onChange={(e) => void onFile(e.target.files?.[0])}
          className="text-sm"
        />
        {upload && (
          <span role="status" className="text-xs opacity-70">
            {upload}
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
    </section>
  );
}
