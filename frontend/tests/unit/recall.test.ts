import { describe, expect, it } from "vitest";
import {
  initialViewState,
  reduceEvent,
  type NoteCard,
  type ServerEvent,
  type ViewState,
} from "@/lib/events";

const run = (
  events: ServerEvent[],
  from: ViewState = initialViewState,
): ViewState => events.reduce(reduceEvent, from);

const quiz = (
  over: Partial<Extract<ServerEvent, { type: "quiz" }>> = {},
): ServerEvent => ({
  type: "quiz",
  phase: "asking",
  item_id: "i1",
  note_id: "n1",
  note_title: "RAG",
  prompt: "What does RAG do?",
  tier: 0,
  hint: null,
  answer: null,
  grade: null,
  fragile: false,
  next_due: null,
  position: 1,
  total: 2,
  summary: null,
  ...over,
});

const note = (id: string): NoteCard => ({
  noteId: id,
  title: id,
  bodyMd: id,
  origin: "user",
  confirmed: true,
  fragile: false,
  change: null,
});

describe("quiz events", () => {
  it("shows the question and keeps the answer hidden until it is revealed", () => {
    const s = run([quiz()]);
    expect(s.quiz).toMatchObject({
      phase: "asking",
      prompt: "What does RAG do?",
      tier: 0,
      answer: null,
    });
    expect(s.focusNoteId).toBe("n1");
  });

  it("climbs the hint ladder and reveals the answer at tier 3", () => {
    const s = run([
      quiz(),
      quiz({ phase: "hint", tier: 1, hint: "Think about retrieval." }),
      quiz({ phase: "hint", tier: 2, hint: "It starts with ret…" }),
      quiz({
        phase: "hint",
        tier: 3,
        hint: "The answer is…",
        answer: "retrieves context",
      }),
    ]);
    expect(s.quiz).toMatchObject({
      phase: "hint",
      tier: 3,
      answer: "retrieves context",
    });
  });

  it("records each grade, marks fragile notes, and starts the next question", () => {
    const s = run(
      [
        quiz({
          phase: "graded",
          tier: 3,
          grade: "Again",
          fragile: true,
          answer: "x",
          position: 1,
        }),
        quiz({ position: 2, item_id: "i2", prompt: "Second?" }),
      ],
      { ...initialViewState, notes: [note("n1")] },
    );
    expect(s.quizResults).toEqual([
      {
        itemId: "i1",
        prompt: "What does RAG do?",
        tier: 3,
        grade: "Again",
        fragile: true,
      },
    ]);
    expect(s.notes[0].fragile).toBe(true);
    expect(s.quiz).toMatchObject({
      phase: "asking",
      prompt: "Second?",
      position: 2,
    });
  });

  it("starting a new quiz clears the previous grades, and ending keeps the summary", () => {
    const first = run([quiz({ phase: "graded", tier: 0, grade: "Good" })]);
    expect(first.quizResults).toHaveLength(1);
    const fresh = reduceEvent(first, quiz({ position: 1 }));
    expect(fresh.quizResults).toEqual([]);

    const ended = reduceEvent(fresh, {
      ...quiz({ phase: "ended", item_id: null, note_id: null, prompt: null }),
      summary: { total: 1, unaided: 1, hinted: 0, revealed: 0, fragile: 0 },
    } as ServerEvent);
    expect(ended.quiz?.phase).toBe("ended");
    expect(ended.quiz?.summary?.unaided).toBe(1);
  });

  it("shows an empty state with the next due time", () => {
    const s = run([
      quiz({
        phase: "empty",
        item_id: null,
        note_id: null,
        prompt: null,
        next_due: "2030-01-01T00:00:00Z",
      }),
    ]);
    expect(s.quiz).toMatchObject({
      phase: "empty",
      nextDue: "2030-01-01T00:00:00Z",
    });
  });
});

describe("explain, read-back, confusion and mode", () => {
  it("keeps the latest explanation with its diagram", () => {
    const s = run([
      {
        type: "explain",
        explain_id: "e1",
        topic: "RAG",
        simple: false,
        text: "What it is…",
        diagram: {
          note_id: "n1",
          kind: "mermaid",
          source: "flowchart TD\n A --> B",
        },
        note_id: "n1",
      },
    ]);
    expect(s.explanation).toMatchObject({
      topic: "RAG",
      simple: false,
      saved: false,
    });
    expect(s.explanation?.diagram?.kind).toBe("mermaid");
  });

  it("tracks read-back progress and clears it when the mode leaves read_back", () => {
    const reading = run([
      { type: "mode", mode: "read_back" },
      {
        type: "read_back",
        index: 0,
        total: 3,
        note_id: "n1",
        title: "A",
        body_md: "a",
        why: "w",
        speed: 0.85,
        finished: false,
      },
    ]);
    expect(reading.readBack).toEqual({
      index: 0,
      total: 3,
      title: "A",
      speed: 0.85,
    });
    expect(reading.focusNoteId).toBe("n1");
    expect(
      reduceEvent(reading, { type: "mode", mode: "capture" }).readBack,
    ).toBeNull();
  });

  it("marks the confused note fragile and clears the notice on the next user turn", () => {
    const s = run(
      [{ type: "confusion", trigger: "phrase: i don't get", note_id: "n1" }],
      {
        ...initialViewState,
        notes: [note("n1"), note("n2")],
      },
    );
    expect(s.notes.map((n) => n.fragile)).toEqual([true, false]);
    expect(s.confusion).toBe("phrase: i don't get");
    const next = reduceEvent(s, {
      type: "utterance",
      id: "u",
      speaker: "user",
      text: "ok",
    });
    expect(next.confusion).toBeNull();
  });

  it("follows the conversation mode", () => {
    expect(run([{ type: "mode", mode: "recall_quiz" }]).mode).toBe(
      "recall_quiz",
    );
  });
});
