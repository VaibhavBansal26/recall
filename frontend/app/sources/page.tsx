"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { SourceCard } from "@/components/SourceCard";
import {
  ACTIVE_STATUSES,
  addSource,
  listSources,
  listTracks,
  uploadPdf,
  type SourceOut,
  type TrackOut,
} from "@/lib/api";
import { looksLikeLink } from "@/lib/sources";
import { useRefreshOnFocus } from "@/lib/useRefreshOnFocus";

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceOut[]>([]);
  const [tracks, setTracks] = useState<TrackOut[]>([]);
  const [input, setInput] = useState("");
  const [track, setTrack] = useState("");
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setSources(await listSources());
    } catch {
      /* keep what we have */
    }
  }, []);

  useEffect(() => {
    void refresh();
    listTracks().then(setTracks).catch(() => undefined);
  }, [refresh]);
  useRefreshOnFocus(refresh);

  // Poll quickly while anything is being processed.
  const working = sources.some((s) => ACTIVE_STATUSES.includes(s.status));
  useEffect(() => {
    if (!working) return;
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [working, refresh]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setBusy(true);
    setMessage(null);
    const result = await addSource(input, track || null);
    setBusy(false);
    if (!result.ok) return setMessage({ kind: "error", text: result.error });
    setInput("");
    if (result.source.deduplicated) {
      setMessage({ kind: "info", text: "You already added that one, so it was not added twice." });
    }
    await refresh();
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setMessage(null);
    const result = await uploadPdf(file, track || null);
    setBusy(false);
    if (fileInput.current) fileInput.current.value = "";
    if (!result.ok) return setMessage({ kind: "error", text: result.error });
    if (result.source.deduplicated) setMessage({ kind: "info", text: "That file was already added." });
    await refresh();
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-5 p-6">
      <header>
        <h1 className="text-xl font-semibold">Sources</h1>
        <p className="text-sm opacity-70">
          Add a link, a YouTube video, a PDF or pasted text. Recall files it into notes with citations,
          and nothing counts until you approve it.
        </p>
      </header>

      <form onSubmit={submit} className="flex flex-col gap-3 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
        <label className="flex flex-col gap-1 text-sm">
          Link or text
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={looksLikeLink(input) || input === "" ? 2 : 5}
            placeholder="https://… or paste an article"
            className="rounded-lg border border-neutral-300 bg-transparent px-3 py-2 text-base dark:border-neutral-700"
          />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm">
            Track
            <select
              value={track}
              onChange={(e) => setTrack(e.target.value)}
              className="min-h-11 rounded-lg border border-neutral-300 bg-transparent px-2 dark:border-neutral-700"
            >
              <option value="">Work it out for me</option>
              {tracks.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white disabled:opacity-40"
          >
            Add source
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
            className="min-h-11 rounded-lg border border-neutral-300 px-4 py-2 dark:border-neutral-700"
          >
            Upload PDF
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            aria-label="PDF file"
            className="hidden"
            onChange={(e) => void onFile(e.target.files?.[0])}
          />
        </div>
        {message && (
          <p
            role={message.kind === "error" ? "alert" : "status"}
            className={message.kind === "error" ? "text-sm text-red-600 dark:text-red-400" : "text-sm opacity-80"}
          >
            {message.text}
          </p>
        )}
      </form>

      {sources.length === 0 ? (
        <p className="text-sm opacity-60">Nothing here yet.</p>
      ) : (
        <ul aria-label="Sources" className="flex flex-col gap-3">
          {sources.map((s) => (
            <SourceCard key={s.id} source={s} tracks={tracks} onChanged={() => void refresh()} />
          ))}
        </ul>
      )}
    </main>
  );
}
