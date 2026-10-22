import { describe, expect, it } from "vitest";
import {
  applyCaptureItems,
  applyUndo,
  initialViewState,
  mergeNotes,
  reduceEvent,
  type CaptureItem,
  type NoteCard,
  type ServerEvent,
  type ViewState,
} from "@/lib/events";

const run = (events: ServerEvent[], from: ViewState = initialViewState): ViewState =>
  events.reduce(reduceEvent, from);

const item = (over: Partial<CaptureItem> = {}): CaptureItem => ({
  event_id: "e1",
  action: "created",
  similarity: null,
  note_id: "n1",
  title: "RAG retrieves first",
  body_md: "RAG retrieves first.",
  origin: "user",
  confirmed: true,
  before_title: null,
  before_body_md: null,
  ...over,
});

describe("transcript and turn flow", () => {
  it("starts a fresh conversation on session but keeps loaded notes", () => {
    const withNotes = run([{ type: "notes", items: [item()] }]);
    const state = run(
      [{ type: "session", session_id: "s1", track: "ai-eng", audio_input: true }],
      withNotes,
    );
    expect(state).toMatchObject({ sessionId: "s1", audioInput: true, utterances: [] });
    expect(state.notes).toHaveLength(1);
  });

  it("shows live partials and clears them when the stored utterance arrives", () => {
    const mid = run([{ type: "transcript", text: "rag retrieves", final: false }]);
    expect(mid.partial).toBe("rag retrieves");
    const done = reduceEvent(mid, { type: "utterance", id: "u1", speaker: "user", text: "x" });
    expect(done.partial).toBe("");
    expect(done.phase).toBe("thinking");
  });

  it("streams assistant sentences into a draft, then replaces it with the stored utterance", () => {
    const mid = run([
      { type: "utterance", id: "u1", speaker: "user", text: "hi" },
      { type: "assistant_delta", text: "Got it." },
      { type: "assistant_delta", text: "Keep going." },
    ]);
    expect(mid.assistantDraft).toBe("Got it. Keep going.");
    expect(mid.phase).toBe("speaking");

    const done = run(
      [
        { type: "utterance", id: "u2", speaker: "assistant", text: "Got it. Keep going." },
        { type: "assistant_done" },
      ],
      mid,
    );
    expect(done.assistantDraft).toBe("");
    expect(done.phase).toBe("idle");
    expect(done.utterances.map((u) => u.speaker)).toEqual(["user", "assistant"]);
  });

  it("marks an interrupted assistant turn and clears the draft", () => {
    const state = run([
      { type: "assistant_delta", text: "Partial" },
      { type: "interrupted" },
      { type: "utterance", id: "u", speaker: "assistant", text: "Partial", interrupted: true },
    ]);
    expect(state.assistantDraft).toBe("");
    expect(state.utterances[0].interrupted).toBe(true);
  });

  it("records latency and surfaces errors, clearing them on the next utterance", () => {
    const state = run([
      {
        type: "latency",
        stt_to_first_token_ms: 300,
        first_token_to_audio_ms: 200,
        stt_to_first_audio_ms: 500,
      },
      { type: "error", message: "boom" },
    ]);
    expect(state.latency?.sttToFirstAudioMs).toBe(500);
    expect(state.error).toBe("boom");
    expect(reduceEvent(state, { type: "utterance", id: "u", speaker: "user", text: "x" }).error).toBeNull();
  });
});

describe("notes", () => {
  it("adds created notes at the top", () => {
    const notes = applyCaptureItems(
      applyCaptureItems([], [item()]),
      [item({ event_id: "e2", note_id: "n2", title: "Second" })],
    );
    expect(notes.map((n) => n.noteId)).toEqual(["n2", "n1"]);
  });

  it("updates a merged note in place instead of adding a duplicate", () => {
    const notes = applyCaptureItems(applyCaptureItems([], [item()]), [
      item({
        event_id: "e2",
        action: "merged",
        similarity: 0.93,
        body_md: "RAG retrieves first, then generates.",
        before_body_md: "RAG retrieves first.",
      }),
    ]);
    expect(notes).toHaveLength(1);
    expect(notes[0].bodyMd).toBe("RAG retrieves first, then generates.");
    expect(notes[0].change).toMatchObject({ action: "merged", beforeBodyMd: "RAG retrieves first." });
  });

  it("undo removes a created note and restores a merged one", () => {
    const created = applyCaptureItems([], [item()]);
    expect(applyUndo(created, "e1")).toEqual([]);

    const merged = applyCaptureItems(created, [
      item({
        event_id: "e2",
        action: "merged",
        title: "New title",
        body_md: "merged",
        before_title: "RAG retrieves first",
        before_body_md: "RAG retrieves first.",
      }),
    ]);
    const restored = applyUndo(merged, "e2");
    expect(restored[0]).toMatchObject({
      title: "RAG retrieves first",
      bodyMd: "RAG retrieves first.",
      change: null,
    });
  });

  it("flags unconfirmed assistant notes", () => {
    const notes = applyCaptureItems([], [item({ origin: "assistant", confirmed: false })]);
    expect(notes[0]).toMatchObject({ origin: "assistant", confirmed: false });
  });
});

describe("diagrams and links", () => {
  const diagram = { note_id: "n1", kind: "mermaid" as const, source: "flowchart TD\n  A --> B" };
  const link = {
    id: "l1",
    from_note_id: "n1",
    to_note_id: "n2",
    from_title: "A",
    to_title: "B",
    kind: "related" as const,
    origin: "assistant" as const,
    confirmed: false,
  };

  it("keeps the latest diagram per note", () => {
    const state = run([
      { type: "diagram", items: [diagram] },
      { type: "diagram", items: [{ ...diagram, kind: "steps", source: "one\ntwo" }] },
    ]);
    expect(Object.keys(state.diagrams)).toEqual(["n1"]);
    expect(state.diagrams.n1.kind).toBe("steps");
  });

  it("collects assistant links as unconfirmed and ignores repeats", () => {
    const state = run([
      { type: "links", items: [link] },
      { type: "links", items: [link] },
    ]);
    expect(state.links).toHaveLength(1);
    expect(state.links[0]).toMatchObject({ origin: "assistant", confirmed: false });
  });

  it("keeps diagrams and links when a new session starts", () => {
    const before = run([
      { type: "diagram", items: [diagram] },
      { type: "links", items: [link] },
    ]);
    const after = reduceEvent(before, {
      type: "session",
      session_id: "s2",
      track: "ai-eng",
      audio_input: false,
    });
    expect(Object.keys(after.diagrams)).toEqual(["n1"]);
    expect(after.links).toHaveLength(1);
  });
});

describe("mergeNotes", () => {
  const card = (id: string, title: string, change: NoteCard["change"] = null): NoteCard => ({
    noteId: id,
    title,
    bodyMd: title,
    origin: "user",
    confirmed: true,
    fragile: false,
    change,
  });
  const change = { eventId: "e1", action: "created" as const, similarity: null, beforeTitle: null, beforeBodyMd: null };

  it("takes the server's notes but keeps undo info for ones captured here", () => {
    const merged = mergeNotes([card("a", "old", change)], [card("b", "from phone"), card("a", "new")]);
    expect(merged.map((n) => n.noteId)).toEqual(["b", "a"]);
    expect(merged[1]).toMatchObject({ title: "new", change });
    expect(merged[0].change).toBeNull();
  });

  it("drops notes that were deleted elsewhere", () => {
    expect(mergeNotes([card("a", "x", change)], [])).toEqual([]);
  });
});

describe("teach-back events", () => {
  const base = {
    type: "teachback" as const,
    topic: "how an index works",
    words: 0,
    ideas: [],
    metrics: null,
    beats: null,
    clarity: null,
    structure: null,
    clarity_reason: "",
    well_done: "",
    to_fix: "",
    suggestions: [],
    rewrite: null,
  };

  it("shows the live word count while listening", () => {
    const listening = reduceEvent(initialViewState, { ...base, phase: "listening", words: 12 });
    expect(listening.teachBack).toMatchObject({ phase: "listening", words: 12, topic: "how an index works" });
  });

  it("keeps the scored result, then clears when cancelled", () => {
    const scored = reduceEvent(initialViewState, {
      ...base,
      phase: "scored",
      clarity: 70,
      structure: 75,
      well_done: "Clear start.",
      to_fix: "Say why it matters.",
      rewrite: { original: "it is fast", improved: "it avoids scanning every row" },
    });
    expect(scored.teachBack).toMatchObject({ clarity: 70, structure: 75, toFix: "Say why it matters." });
    expect(reduceEvent(scored, { ...base, phase: "cancelled" }).teachBack).toBeNull();
  });
});

describe("ending the session by voice", () => {
  it("counts each spoken end so the screen can close the mic", () => {
    const once = reduceEvent(initialViewState, { type: "session_end" });
    expect(once.voiceEnds).toBe(1);
    expect(reduceEvent(once, { type: "session_end" }).voiceEnds).toBe(2);
  });
});
