// Mirrors backend/app/voice/events.py (WebSocket events are not in OpenAPI).

export type Speaker = "user" | "assistant";
export type NoteOrigin = "user" | "source" | "assistant";

export type ClientEvent =
  | { type: "start"; track: string; session_id?: string | null }
  | { type: "text"; text: string }
  | { type: "interrupt" }
  | { type: "speech_start" }
  | { type: "end_speech" }
  | { type: "quiz"; note_id?: string | null; brief_id?: string | null }
  | { type: "quiz_action"; action: "hint" | "forgot" | "skip" | "end" }
  | { type: "teachback_start"; topic?: string | null }
  | { type: "teachback_done"; cancel?: boolean };

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
  kind: "mermaid" | "steps" | "walkthrough";
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

export interface QuizSummary {
  total: number;
  unaided: number;
  hinted: number;
  revealed: number;
  fragile: number;
}

export type TeachBackPhase = "listening" | "scoring" | "scored" | "too_short" | "cancelled";
export type BeatName = "what" | "how" | "why" | "impact";

export interface TeachBackMetrics {
  word_count: number;
  duration_s: number | null;
  wpm: number | null;
  filler_count: number;
  filler_rate: number;
  fillers: Record<string, number>;
  long_pauses: number;
  longest_pause_s: number;
  pauses: { after_word: string; seconds: number }[];
  sentences: {
    count: number;
    mean: number;
    median: number;
    longest: number;
    short: number;
    medium: number;
    long: number;
    punctuated: boolean;
  };
}

export type QuizPhase = "asking" | "hint" | "graded" | "ended" | "empty";

export type ServerEvent =
  | { type: "session"; session_id: string; track: string; audio_input: boolean }
  | { type: "transcript"; text: string; final: boolean }
  | { type: "utterance"; id: string; speaker: Speaker; text: string; interrupted?: boolean }
  | { type: "notes"; items: CaptureItem[] }
  | {
      type: "quiz";
      phase: QuizPhase;
      item_id: string | null;
      note_id: string | null;
      note_title: string | null;
      prompt: string | null;
      tier: number;
      hint: string | null;
      answer: string | null;
      grade: string | null;
      fragile: boolean;
      next_due: string | null;
      position: number;
      total: number;
      summary: QuizSummary | null;
    }
  | {
      type: "explain";
      explain_id: string;
      topic: string;
      simple: boolean;
      text: string;
      diagram: DiagramItem | null;
      note_id: string | null;
    }
  | {
      type: "read_back";
      index: number;
      total: number;
      note_id: string | null;
      title: string | null;
      body_md: string | null;
      why: string | null;
      speed: number;
      finished: boolean;
    }
  | {
      type: "teachback";
      phase: TeachBackPhase;
      topic: string;
      words: number;
      ideas: string[];
      metrics: TeachBackMetrics | null;
      beats: Record<BeatName, { present: boolean; evidence: string }> | null;
      clarity: number | null;
      structure: number | null;
      clarity_reason: string;
      well_done: string;
      to_fix: string;
      suggestions: string[];
      rewrite: { original: string; improved: string } | null;
    }
  | { type: "confusion"; trigger: string; note_id: string | null }
  | { type: "mode"; mode: string }
  | { type: "session_end" }
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
  fragile: boolean;
  change: {
    eventId: string;
    action: "created" | "merged";
    similarity: number | null;
    beforeTitle: string | null;
    beforeBodyMd: string | null;
  } | null;
}

export type Phase = "idle" | "thinking" | "speaking";

/** The question currently on screen in a quiz, and where it is on the hint ladder. */
export interface QuizView {
  phase: QuizPhase;
  itemId: string | null;
  noteId: string | null;
  noteTitle: string | null;
  prompt: string | null;
  tier: number;
  hint: string | null;
  answer: string | null;
  grade: string | null;
  fragile: boolean;
  nextDue: string | null;
  position: number;
  total: number;
  summary: QuizSummary | null;
}

export interface QuizResult {
  itemId: string;
  prompt: string;
  tier: number;
  grade: string;
  fragile: boolean;
}

export interface Explanation {
  id: string;
  topic: string;
  simple: boolean;
  text: string;
  diagram: DiagramItem | null;
  noteId: string | null;
  saved: boolean;
}

export interface ReadBackView {
  index: number;
  total: number;
  title: string | null;
  speed: number;
}

export interface TeachBackView {
  phase: TeachBackPhase;
  topic: string;
  words: number;
  ideas: string[];
  metrics: TeachBackMetrics | null;
  beats: Record<BeatName, { present: boolean; evidence: string }> | null;
  clarity: number | null;
  structure: number | null;
  clarityReason: string;
  wellDone: string;
  toFix: string;
  suggestions: string[];
  rewrite: { original: string; improved: string } | null;
}

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
  mode: string;
  quiz: QuizView | null;
  quizResults: QuizResult[];
  explanation: Explanation | null;
  readBack: ReadBackView | null;
  teachBack: TeachBackView | null;
  /** Counts spoken "end the session" commands; the screen turns the mic off when it changes. */
  voiceEnds: number;
  /** The note the assistant is currently talking about (read-back, quiz); the diagram follows it. */
  focusNoteId: string | null;
  /** Set when confusion was detected, so the UI can say the note was marked fragile. */
  confusion: string | null;
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
  mode: "capture",
  quiz: null,
  quizResults: [],
  explanation: null,
  readBack: null,
  teachBack: null,
  voiceEnds: 0,
  focusNoteId: null,
  confusion: null,
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
      fragile: false,
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
        quizResults: [],
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
        confusion: speaker === "user" ? null : state.confusion,
        assistantDraft: speaker === "assistant" ? "" : state.assistantDraft,
        phase: speaker === "user" ? "thinking" : state.phase,
      };
    }
    case "notes":
      return { ...state, notes: applyCaptureItems(state.notes, event.items) };
    case "mode":
      return {
        ...state,
        mode: event.mode,
        readBack: event.mode === "read_back" ? state.readBack : null,
      };
    case "session_end":
      return { ...state, voiceEnds: state.voiceEnds + 1 };
    case "quiz": {
      const view: QuizView = {
        phase: event.phase,
        itemId: event.item_id,
        noteId: event.note_id,
        noteTitle: event.note_title,
        prompt: event.prompt,
        tier: event.tier,
        hint: event.hint,
        answer: event.answer,
        grade: event.grade,
        fragile: event.fragile,
        nextDue: event.next_due,
        position: event.position,
        total: event.total,
        summary: event.summary,
      };
      const focusNoteId = event.note_id ?? state.focusNoteId;
      if (event.phase === "asking") {
        return {
          ...state,
          focusNoteId,
          quiz: view,
          quizResults: event.position === 1 ? [] : state.quizResults,
        };
      }
      if (event.phase === "graded") {
        const result: QuizResult = {
          itemId: event.item_id ?? "",
          prompt: event.prompt ?? "",
          tier: event.tier,
          grade: event.grade ?? "",
          fragile: event.fragile,
        };
        return {
          ...state,
          focusNoteId,
          quiz: view,
          quizResults: [...state.quizResults, result],
          notes: event.fragile
            ? state.notes.map((n) => (n.noteId === event.note_id ? { ...n, fragile: true } : n))
            : state.notes,
        };
      }
      if (event.phase === "ended") {
        return { ...state, quiz: { ...(state.quiz ?? view), ...view, phase: "ended" } };
      }
      return { ...state, focusNoteId, quiz: view };
    }
    case "explain":
      return {
        ...state,
        explanation: {
          id: event.explain_id,
          topic: event.topic,
          simple: event.simple,
          text: event.text,
          diagram: event.diagram,
          noteId: event.note_id,
          saved: false,
        },
      };
    case "read_back":
      return {
        ...state,
        focusNoteId: event.note_id ?? state.focusNoteId,
        readBack: event.finished && event.note_id === null
          ? null
          : { index: event.index, total: event.total, title: event.title, speed: event.speed },
      };
    case "teachback":
      if (event.phase === "cancelled") return { ...state, teachBack: null };
      return {
        ...state,
        teachBack: {
          phase: event.phase,
          topic: event.topic,
          words: event.words,
          ideas: event.ideas,
          metrics: event.metrics,
          beats: event.beats,
          clarity: event.clarity,
          structure: event.structure,
          clarityReason: event.clarity_reason,
          wellDone: event.well_done,
          toFix: event.to_fix,
          suggestions: event.suggestions,
          rewrite: event.rewrite,
        },
      };
    case "confusion":
      return {
        ...state,
        confusion: event.trigger,
        notes: state.notes.map((n) => (n.noteId === event.note_id ? { ...n, fragile: true } : n)),
      };
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
