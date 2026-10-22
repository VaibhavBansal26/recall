"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { DiagramView } from "@/components/DiagramView";
import { MemoryMap } from "@/components/MemoryMap";
import {
  deleteLink,
  getDiagram,
  getGraph,
  getNoteLinks,
  listTracks,
  setLinkConfirmed,
  type GraphOut,
  type LinkOut,
  type TrackOut,
} from "@/lib/api";
import type { DiagramItem } from "@/lib/events";
import { strengthColor } from "@/lib/layout";
import { useRefreshOnFocus } from "@/lib/useRefreshOnFocus";

const EMPTY: GraphOut = { nodes: [], edges: [] };

export default function MapPage() {
  const [tracks, setTracks] = useState<TrackOut[]>([]);
  const [track, setTrack] = useState<string>("ai-eng");
  const [graph, setGraph] = useState<GraphOut>(EMPTY);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setGraph(await getGraph(track || undefined));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the map");
    }
  }, [track]);

  useEffect(() => {
    listTracks().then(setTracks).catch(() => undefined);
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useRefreshOnFocus(refresh);

  const node = graph.nodes.find((n) => n.id === selected) ?? null;
  const unconfirmed = graph.edges.filter((e) => !e.confirmed).length;

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Memory map</h1>
          <p className="text-sm opacity-70">
            <span data-testid="map-count">{graph.nodes.length}</span> notes ·{" "}
            {graph.edges.length} links
            {unconfirmed > 0 && ` · ${unconfirmed} unconfirmed`}
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          Track
          <select
            value={track}
            onChange={(e) => {
              setTrack(e.target.value);
              setSelected(null);
            }}
            className="rounded-lg border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
          >
            <option value="">All tracks</option>
            {tracks.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
        <div className="h-[60vh] min-h-[22rem] overflow-hidden rounded-xl border border-neutral-200 dark:border-neutral-800">
          {graph.nodes.length === 0 ? (
            <p className="p-4 text-sm opacity-60">
              No notes yet. Capture some in a session and they appear here.
            </p>
          ) : (
            <MemoryMap graph={graph} selectedId={selected} onSelect={setSelected} />
          )}
        </div>
        <aside aria-label="Note details" className="flex flex-col gap-4">
          {node ? (
            <NoteDetails
              key={node.id}
              node={node}
              onChanged={refresh}
              edges={graph.edges}
            />
          ) : (
            <Legend />
          )}
        </aside>
      </div>
    </main>
  );
}

function Legend() {
  return (
    <section className="flex flex-col gap-3 text-sm" aria-label="Legend">
      <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Legend</h2>
      <div>
        <div
          className="h-3 rounded"
          style={{
            background: `linear-gradient(to right, ${strengthColor(0)}, ${strengthColor(0.5)}, ${strengthColor(1)})`,
          }}
        />
        <div className="mt-1 flex justify-between text-xs opacity-70">
          <span>forgotten</span>
          <span>strong</span>
        </div>
        <p className="mt-1 text-xs opacity-60">
          Grey notes have no review history yet. Colours fill in as you answer quiz questions.
        </p>
      </div>
      <p>
        <span className="mr-1 text-red-600">⚠</span> red border = fragile (you struggled with it)
      </p>
      <p>
        <span className="text-amber-600">- - -</span> dashed amber = link proposed by the assistant,
        not confirmed yet
      </p>
      <p className="opacity-70">Click a note to open it, its diagram and its links.</p>
    </section>
  );
}

function NoteDetails({
  node,
  edges,
  onChanged,
}: {
  node: GraphOut["nodes"][number];
  edges: LinkOut[];
  onChanged: () => Promise<void>;
}) {
  const router = useRouter();
  const [diagram, setDiagram] = useState<DiagramItem | null | undefined>(undefined);
  const [links, setLinks] = useState<LinkOut[]>([]);

  const loadLinks = useCallback(async () => {
    setLinks(await getNoteLinks(node.id));
  }, [node.id]);

  useEffect(() => {
    getDiagram(node.id).then(setDiagram).catch(() => setDiagram(null));
    loadLinks().catch(() => undefined);
    // Edges change when a link is confirmed/removed, so re-read the note's links too.
  }, [node.id, loadLinks, edges]);

  async function act(fn: () => Promise<unknown>) {
    await fn();
    await Promise.all([loadLinks(), onChanged()]);
  }

  return (
    <div className="flex flex-col gap-4 text-sm">
      <section aria-label="Note">
        <h2 className="font-semibold">{node.title}</h2>
        <p className="mt-1 whitespace-pre-wrap opacity-90">{node.body_md}</p>
        {node.fragile && <p className="mt-1 text-red-600">⚠ Fragile: you struggled with this one</p>}
        <button
          type="button"
          onClick={() => router.push(`/review?note=${node.id}`)}
          className="mt-3 min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white"
        >
          Quiz me on this
        </button>
      </section>

      <section aria-label="Diagram">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-60">Diagram</h3>
        {diagram === undefined ? (
          <p className="opacity-60">Loading…</p>
        ) : diagram ? (
          <DiagramView diagram={diagram} />
        ) : (
          <p className="opacity-60">No diagram yet.</p>
        )}
      </section>

      <section aria-label="Links">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-60">Links</h3>
        {links.length === 0 ? (
          <p className="opacity-60">No links.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {links.map((l) => {
              const outgoing = l.from_note_id === node.id;
              return (
                <li
                  key={l.id}
                  className={`rounded-lg border p-2 ${
                    l.confirmed
                      ? "border-neutral-200 dark:border-neutral-800"
                      : "border-dashed border-amber-500/70 bg-amber-50 dark:bg-amber-950/20"
                  }`}
                >
                  <div>
                    <span className="opacity-60">
                      {outgoing ? `${l.kind.replace("_", " ")} →` : `← ${l.kind.replace("_", " ")}`}
                    </span>{" "}
                    {outgoing ? l.to_title : l.from_title}
                  </div>
                  <div className="mt-1 flex gap-2 text-xs">
                    {!l.confirmed && (
                      <>
                        <span className="text-amber-700 dark:text-amber-300">
                          Proposed by assistant
                        </span>
                        <button
                          type="button"
                          onClick={() => act(() => setLinkConfirmed(l.id, true))}
                          className="rounded border border-neutral-300 px-2 py-0.5 dark:border-neutral-700"
                        >
                          Confirm
                        </button>
                      </>
                    )}
                    <button
                      type="button"
                      onClick={() => act(() => deleteLink(l.id))}
                      className="rounded border border-neutral-300 px-2 py-0.5 dark:border-neutral-700"
                    >
                      Remove
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
