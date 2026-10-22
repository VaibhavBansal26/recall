import type { components } from "./api-types";
import type { DiagramItem, NoteCard } from "./events";
import { apiFetch } from "./http";

export type SessionDetail = components["schemas"]["SessionDetail"];
export type NoteOut = components["schemas"]["NoteOut"];

export async function getSession(id: string): Promise<SessionDetail> {
  const res = await apiFetch(`/api/sessions/${id}`);
  if (!res.ok) throw new Error(`GET session failed: ${res.status}`);
  return (await res.json()) as SessionDetail;
}

export function toNoteCard(n: NoteOut): NoteCard {
  return {
    noteId: n.id,
    title: n.title,
    bodyMd: n.body_md,
    origin: n.origin,
    confirmed: n.confirmed,
    fragile: n.fragile ?? false,
    change: null,
  };
}

export async function listNotes(track: string): Promise<NoteCard[]> {
  const res = await apiFetch(`/api/notes?track=${encodeURIComponent(track)}`);
  if (!res.ok) throw new Error(`GET notes failed: ${res.status}`);
  return ((await res.json()) as NoteOut[]).map(toNoteCard);
}

export async function undoCapture(eventId: string): Promise<void> {
  const res = await apiFetch(`/api/capture-events/${eventId}/undo`, { method: "POST" });
  if (!res.ok) throw new Error(`Undo failed: ${res.status}`);
}

export type GraphOut = components["schemas"]["GraphOut"];
export type GraphNode = components["schemas"]["GraphNode"];
export type LinkOut = components["schemas"]["LinkOut"];
export type TrackOut = components["schemas"]["TrackOut"];

async function json<T>(res: Response, what: string): Promise<T> {
  if (!res.ok) throw new Error(`${what} failed: ${res.status}`);
  return (await res.json()) as T;
}

export async function listTracks(): Promise<TrackOut[]> {
  return json(await apiFetch(`/api/tracks`), "GET tracks");
}

export async function getGraph(track?: string): Promise<GraphOut> {
  const q = track ? `?track=${encodeURIComponent(track)}` : "";
  return json(await apiFetch(`/api/graph${q}`), "GET graph");
}

/** Null when the note has no diagram yet. */
export async function getDiagram(noteId: string): Promise<DiagramItem | null> {
  const res = await apiFetch(`/api/notes/${noteId}/diagram`);
  if (res.status === 404) return null;
  const d = await json<components["schemas"]["DiagramOut"]>(res, "GET diagram");
  return { note_id: d.note_id, kind: d.kind, source: d.source };
}

export async function regenerateDiagram(noteId: string): Promise<DiagramItem> {
  const res = await apiFetch(`/api/notes/${noteId}/diagram/regenerate`, { method: "POST" });
  const d = await json<components["schemas"]["DiagramOut"]>(res, "Regenerate diagram");
  return { note_id: d.note_id, kind: d.kind, source: d.source };
}

export async function getNoteLinks(noteId: string): Promise<LinkOut[]> {
  return json(await apiFetch(`/api/notes/${noteId}/links`), "GET links");
}

export async function setLinkConfirmed(linkId: string, confirmed: boolean): Promise<LinkOut> {
  const res = await apiFetch(`/api/links/${linkId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed }),
  });
  return json(res, "PATCH link");
}

export async function deleteLink(linkId: string): Promise<void> {
  const res = await apiFetch(`/api/links/${linkId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`DELETE link failed: ${res.status}`);
}

export type DueOut = components["schemas"]["DueOut"];

export async function getDue(track?: string): Promise<DueOut> {
  const q = track ? `?track=${encodeURIComponent(track)}&limit=1` : "?limit=1";
  return json(await apiFetch(`/api/reviews/due${q}`), "GET due");
}

/** Save something the assistant said (an explanation) as an unconfirmed assistant note. */
export async function saveAssistantNote(track: string, title: string, body: string): Promise<NoteOut> {
  const res = await apiFetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ track, title, body_md: body, origin: "assistant" }),
  });
  return json(res, "POST note");
}

export async function setNoteConfirmed(noteId: string, confirmed: boolean): Promise<NoteOut> {
  const res = await apiFetch(`/api/notes/${noteId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmed }),
  });
  return json(res, "PATCH note");
}
