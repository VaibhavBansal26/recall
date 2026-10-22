// Mirrors backend/app/voice/events.py (WebSocket events are not in OpenAPI).

export type Speaker = "user" | "assistant";
export type NoteOrigin = "user" | "source" | "assistant";

export type ClientEvent =
  | { type: "start"; track: string; session_id?: string | null }
  | { type: "text"; text: string }
  | { type: "interrupt" }
  | { type: "speech_start" }
  | { type: "end_speech" };

export interface CaptureItem {
  event_id: string;
  action: "created" | "merged";
  similarity: number | null;
  note_id: string;
  title: string;
  body_md: string;
  origin: NoteOrigin;
  confirmed: boolean;
  before_title: string | null;
  before_body_md: string | null;
}

export interface DiagramItem {
  note_id: string;
  kind: "mermaid" | "steps";
  source: string;
}

export type LinkKind = "prerequisite" | "related" | "example_of" | "contrasts" | "appears_in";

export interface LinkItem {
  id: string;
  from_note_id: string;
  to_note_id: string;
  from_title: string;
  to_title: string;
  kind: LinkKind;
  origin: NoteOrigin;
  confirmed: boolean;
}

export type ServerEvent =
  | { type: "session"; session_id: string; track: string; audio_input: boolean }
  | { type: "transcript"; text: string; final: boolean }
  | { type: "utterance"; id: string; speaker: Speaker; text: string; interrupted?: boolean }
  | { type: "notes"; items: CaptureItem[] }
  | { type: "diagram"; items: DiagramItem[] }
  | { type: "links"; items: LinkItem[] }
  | {
      type: "latency";
      stt_to_first_token_ms: number | null;
      first_token_to_audio_ms: number | null;
      stt_to_first_audio_ms: number | null;
    }
  | { type: "assistant_delta"; text: string }
  | { type: "audio"; format: "pcm_s16le_16000"; data: string }
  | { type: "assistant_done" }
  | { type: "interrupted" }
  | { type: "error"; message: string };

export interface StoredUtterance {
  id: string;
  speaker: Speaker;
  text: string;
  interrupted: boolean;
}

/** A note as shown in the notes pane, plus what the last capture did to it (for undo). */
export interface NoteCard {
  noteId: string;
  title: string;
  bodyMd: string;
  origin: NoteOrigin;
  confirmed: boolean;
  change: {
    eventId: string;
    action: "created" | "merged";
    similarity: number | null;
    beforeTitle: string | null;
    beforeBodyMd: string | null;
  } | null;
}

export type Phase = "idle" | "thinking" | "speaking";

export interface Latency {
  sttToFirstTokenMs: number | null;
  firstTokenToAudioMs: number | null;
  sttToFirstAudioMs: number | null;
}

export interface ViewState {
  sessionId: string | null;
  track: string | null;
  audioInput: boolean;
  utterances: StoredUtterance[];
  /** Live transcript of what the user is saying right now. */
  partial: string;
  /** Assistant sentences streamed so far for the turn in flight. */
  assistantDraft: string;
  phase: Phase;
  notes: NoteCard[];
  /** Latest diagram per note id. */
  diagrams: Record<string, DiagramItem>;
  /** Links seen this session; assistant ones are unconfirmed until accepted. */
  links: LinkItem[];
  latency: Latency | null;
  error: string | null;
}

export const initialViewState: ViewState = {
  sessionId: null,
  track: null,
  audioInput: false,
  utterances: [],
  partial: "",
  assistantDraft: "",
  phase: "idle",
  notes: [],
  diagrams: {},
  links: [],
  latency: null,
  error: null,
};

export function applyCaptureItems(notes: NoteCard[], items: CaptureItem[]): NoteCard[] {
  let next = notes;
  for (const item of items) {
    const card: NoteCard = {
      noteId: item.note_id,
      title: item.title,
      bodyMd: item.body_md,
      origin: item.origin,
      confirmed: item.confirmed,
      change: {
        eventId: item.event_id,
        action: item.action,
        similarity: item.similarity,
        beforeTitle: item.before_title,
        beforeBodyMd: item.before_body_md,
      },
    };
    const exists = next.some((n) => n.noteId === item.note_id);
    next = exists
      ? next.map((n) => (n.noteId === item.note_id ? card : n))
      : [card, ...next];
  }
  return next;
}

/** Reflect a successful undo: drop a created note, restore a merged one. */
export function applyUndo(notes: NoteCard[], eventId: string): NoteCard[] {
  return notes.flatMap((n) => {
    if (n.change?.eventId !== eventId) return [n];
    if (n.change.action === "created") return [];
    return [
      {
        ...n,
        title: n.change.beforeTitle ?? n.title,
        bodyMd: n.change.beforeBodyMd ?? n.bodyMd,
        change: null,
      },
    ];
  });
}

export function reduceEvent(state: ViewState, event: ServerEvent): ViewState {
  switch (event.type) {
    case "session":
      return {
        ...initialViewState,
        notes: state.notes,
        diagrams: state.diagrams,
        links: state.links,
        sessionId: event.session_id,
        track: event.track,
        audioInput: event.audio_input,
      };
    case "transcript":
      return { ...state, partial: event.final ? "" : event.text };
    case "utterance": {
      const { id, speaker, text } = event;
      const stored: StoredUtterance = { id, speaker, text, interrupted: event.interrupted ?? false };
      return {
        ...state,
        error: null,
        utterances: [...state.utterances, stored],
        partial: speaker === "user" ? "" : state.partial,
        assistantDraft: speaker === "assistant" ? "" : state.assistantDraft,
        phase: speaker === "user" ? "thinking" : state.phase,
      };
    }
    case "notes":
      return { ...state, notes: applyCaptureItems(state.notes, event.items) };
    case "diagram":
      return {
        ...state,
        diagrams: {
          ...state.diagrams,
          ...Object.fromEntries(event.items.map((d) => [d.note_id, d])),
        },
      };
    case "links": {
      const known = new Set(state.links.map((l) => l.id));
      return { ...state, links: [...state.links, ...event.items.filter((l) => !known.has(l.id))] };
    }
    case "latency":
      return {
        ...state,
        latency: {
          sttToFirstTokenMs: event.stt_to_first_token_ms,
          firstTokenToAudioMs: event.first_token_to_audio_ms,
          sttToFirstAudioMs: event.stt_to_first_audio_ms,
        },
      };
    case "assistant_delta":
      return {
        ...state,
        phase: "speaking",
        assistantDraft: state.assistantDraft ? `${state.assistantDraft} ${event.text}` : event.text,
      };
    case "assistant_done":
      return { ...state, phase: "idle" };
    case "interrupted":
      return { ...state, assistantDraft: "", phase: "idle" };
    case "error":
      return { ...state, error: event.message };
    case "audio":
      return state; // played by PcmPlayer, not part of view state
  }
}

/**
 * Replace the notes list with the server's copy (so edits made on another device show up) while
 * keeping the undo info for notes captured in this session.
 */
export function mergeNotes(current: NoteCard[], fetched: NoteCard[]): NoteCard[] {
  const byId = new Map(current.map((n) => [n.noteId, n]));
  return fetched.map((n) => ({ ...n, change: byId.get(n.noteId)?.change ?? null }));
}
