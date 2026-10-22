"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { DebugOverlay } from "@/components/DebugOverlay";
import { DiagramPane } from "@/components/DiagramPane";
import { ExplainCard } from "@/components/ExplainCard";
import { HintLadder } from "@/components/HintLadder";
import { NotePane } from "@/components/NotePane";
import { ReadBackBar } from "@/components/ReadBackBar";
import { TranscriptStream } from "@/components/TranscriptStream";
import { VoiceOrb, type OrbState } from "@/components/VoiceOrb";
import { getDiagram, getDue, listNotes, setNoteConfirmed, undoCapture } from "@/lib/api";
import { MicCapture, PcmPlayer } from "@/lib/audio";
import type { ServerEvent } from "@/lib/events";
import { useSessionStore } from "@/lib/store";
import { useRefreshOnFocus } from "@/lib/useRefreshOnFocus";
import { VoiceSocket } from "@/lib/ws";

const TRACK = "ai-eng";
const STATUS_LABEL = { connecting: "Connecting", connected: "Connected", closed: "Disconnected" };

type MicMode = "off" | "open" | "ptt";

interface Props {
  /** "review" opens on the quiz; "session" is the free conversation screen. */
  variant?: "session" | "review";
  /** Start a quiz as soon as the session is ready (from /review or the map's button). */
  autoQuiz?: boolean;
  /** Practise this one note instead of whatever is due. */
  quizNoteId?: string | null;
}

export function SessionView({ variant = "session", autoQuiz = false, quizNoteId = null }: Props) {
  const s = useSessionStore();
  const { apply, setConnection, setNotes, syncNotes, setDiagram, undone, markSaved } = s;
  const socket = useRef<VoiceSocket | null>(null);
  const [playing, setPlaying] = useState(false);
  const [playerInstance] = useState(() => new PcmPlayer(setPlaying));
  const player = useRef(playerInstance);
  const mic = useRef<MicCapture | null>(null);
  const [text, setText] = useState("");
  const [micMode, setMicMode] = useState<MicMode>("off");
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const [debug, setDebug] = useState(true);
  const [dueCount, setDueCount] = useState<number | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const autoStarted = useRef(false);

  const refreshDue = useCallback(
    () =>
      getDue(TRACK)
        .then((d) => setDueCount(d.total_due))
        .catch(() => undefined),
    [],
  );
  // Pick up notes and due counts changed on another device when this one comes to the foreground.
  useRefreshOnFocus(() => {
    void listNotes(TRACK).then(syncNotes).catch(() => undefined);
    void refreshDue();
  });
  useEffect(() => {
    void refreshDue();
  }, [refreshDue, s.quiz?.phase]);

  // The diagram pane follows what the assistant is talking about, else the newest note.
  useEffect(() => {
    if (s.focusNoteId) setPicked(s.focusNoteId);
  }, [s.focusNoteId]);
  const selectedNote = s.notes.find((n) => n.noteId === picked) ?? s.notes[0] ?? null;
  const selectedId = selectedNote?.noteId ?? null;
  const selectedDiagram = selectedId ? (s.diagrams[selectedId] ?? null) : null;
  useEffect(() => {
    if (selectedId && !selectedDiagram) {
      getDiagram(selectedId)
        .then((d) => d && setDiagram(d))
        .catch(() => undefined);
    }
  }, [selectedId, selectedDiagram, setDiagram]);

  const onEvent = useCallback(
    (event: ServerEvent) => {
      if (event.type === "audio") player.current.enqueue(event.data);
      if (event.type === "interrupted") player.current.flush();
      apply(event);
    },
    [apply],
  );

  useEffect(() => {
    const audioOut = player.current;
    const voice = new VoiceSocket({ onEvent, onStatus: setConnection });
    socket.current = voice;
    voice.connect(TRACK);
    listNotes(TRACK).then(setNotes).catch(() => undefined);

    const capture = new MicCapture({
      onFrame: (pcm) => voice.sendAudio(pcm),
      onSpeaking: (speaking) => {
        setUserSpeaking(speaking);
        if (speaking) {
          // Barge-in: stop playback right now, then tell the server.
          player.current.flush();
          voice.send({ type: "speech_start" });
        }
      },
    });
    mic.current = capture;
    return () => {
      voice.close();
      void capture.stop();
      audioOut.flush();
    };
  }, [onEvent, setConnection, setNotes]);

  const ready = s.connection === "connected" && !!s.sessionId;

  useEffect(() => {
    if (autoQuiz && ready && !autoStarted.current) {
      autoStarted.current = true;
      void player.current.unlock().catch(() => undefined);
      socket.current?.send({ type: "quiz", note_id: quizNoteId });
    }
  }, [autoQuiz, ready, quizNoteId]);

  async function enableMic(mode: Exclude<MicMode, "off">) {
    setMicError(null);
    try {
      await player.current.unlock();
      await mic.current?.start();
      if (mic.current) mic.current.streaming = true;
      setMicMode(mode);
    } catch (err) {
      setMicError(err instanceof Error ? err.message : "Could not open the microphone");
    }
  }

  async function disableMic() {
    if (mic.current) mic.current.streaming = false;
    setUserSpeaking(false);
    setMicMode("off");
    await mic.current?.stop();
  }

  function releasePushToTalk() {
    if (micMode !== "ptt") return;
    if (mic.current) mic.current.streaming = false;
    setUserSpeaking(false);
    setMicMode("off");
    socket.current?.send({ type: "end_speech" });
  }

  function interrupt() {
    player.current.flush();
    socket.current?.send({ type: "interrupt" });
  }

  function say(words: string) {
    void player.current.unlock(); // a user gesture, so the reply can be heard
    socket.current?.send({ type: "text", text: words });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    say(trimmed);
    setText("");
  }

  function startQuiz() {
    void player.current.unlock();
    socket.current?.send({ type: "quiz", note_id: quizNoteId });
  }

  async function onUndo(eventId: string) {
    await undoCapture(eventId);
    undone(eventId);
  }

  async function onConfirm(noteId: string) {
    await setNoteConfirmed(noteId, true);
    syncNotes(await listNotes(TRACK));
  }

  const orb: OrbState =
    micMode !== "off" && (userSpeaking || s.partial)
      ? "listening"
      : s.phase === "speaking" || playing
        ? "speaking"
        : s.phase === "thinking"
          ? "thinking"
          : micMode !== "off"
            ? "listening"
            : "idle";

  const showLadder = variant === "review" || s.quiz !== null;
  const ladder = (
    <HintLadder
      quiz={s.quiz}
      results={s.quizResults}
      dueCount={dueCount}
      ready={ready}
      onStart={startQuiz}
      onAction={(action) => socket.current?.send({ type: "quiz_action", action })}
    />
  );

  return (
    <main className="mx-auto grid min-h-screen max-w-5xl gap-6 p-6 pb-6 md:grid-cols-[3fr_2fr] md:pb-48">
      <div className="flex flex-col gap-4">
        <header className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-semibold">{variant === "review" ? "Review" : "Recall"}</h1>
            <p className="text-sm opacity-70">
              Track: AI Engineering (<code>{TRACK}</code>) · mode{" "}
              <span data-testid="mode">{s.mode.replace("_", " ")}</span>
            </p>
          </div>
          <div className="text-right text-xs opacity-70">
            <div data-testid="connection">{STATUS_LABEL[s.connection]}</div>
            <div>
              session <span data-testid="session-id">{s.sessionId ?? "…"}</span>
            </div>
          </div>
        </header>

        {variant === "review" && ladder}

        <VoiceOrb state={orb} />

        {s.readBack && <ReadBackBar readBack={s.readBack} onCommand={say} />}
        {variant === "session" && showLadder && ladder}

        <section className="min-h-[10rem] flex-1 overflow-y-auto" aria-live="polite">
          {s.utterances.length === 0 && !s.partial && !s.assistantDraft ? (
            <p className="opacity-60">
              {s.audioInput
                ? "Open the mic or hold the talk button and start explaining."
                : "Type a message. Try “explain RAG”, “read me my notes on RAG”, or “quiz me”."}
            </p>
          ) : null}
          <TranscriptStream
            utterances={s.utterances}
            partial={s.partial}
            assistantDraft={s.assistantDraft}
          />
        </section>

        {s.confusion && (
          <p
            role="status"
            data-testid="confusion-toast"
            className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
          >
            That sounded confusing, so I marked the note fragile and explained it more simply.
          </p>
        )}
        {s.error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {s.error}
          </p>
        )}
        {micError && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {micError}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            aria-pressed={micMode === "open"}
            disabled={!ready || !s.audioInput}
            onClick={() => (micMode === "open" ? void disableMic() : void enableMic("open"))}
            className="min-h-11 rounded-lg border border-neutral-300 px-4 py-2 aria-pressed:border-emerald-500 aria-pressed:bg-emerald-50 disabled:opacity-40 dark:border-neutral-700 dark:aria-pressed:bg-emerald-950/30"
          >
            {micMode === "open" ? "Mic on (click to stop)" : "Open mic"}
          </button>
          <button
            type="button"
            disabled={!ready || !s.audioInput || micMode === "open"}
            onPointerDown={() => void enableMic("ptt")}
            onPointerUp={releasePushToTalk}
            onPointerLeave={releasePushToTalk}
            onPointerCancel={releasePushToTalk}
            onContextMenu={(e) => e.preventDefault()}
            onKeyDown={(e) => {
              if ((e.key === " " || e.key === "Enter") && !e.repeat) void enableMic("ptt");
            }}
            onKeyUp={(e) => {
              if (e.key === " " || e.key === "Enter") releasePushToTalk();
            }}
            className="min-h-11 touch-none select-none rounded-lg border border-neutral-300 px-4 py-2 disabled:opacity-40 dark:border-neutral-700"
          >
            Hold to talk
          </button>
          <button
            type="button"
            onClick={interrupt}
            disabled={s.phase !== "speaking" && !playing}
            className="min-h-11 rounded-lg border border-neutral-300 px-4 py-2 disabled:opacity-40 dark:border-neutral-700"
          >
            Interrupt
          </button>
          {variant === "session" && !showLadder && (
            <button
              type="button"
              disabled={!ready}
              onClick={startQuiz}
              className="min-h-11 rounded-lg border border-neutral-300 px-4 py-2 disabled:opacity-40 dark:border-neutral-700"
            >
              Quiz me{dueCount ? ` (${dueCount} due)` : ""}
            </button>
          )}
          <button
            type="button"
            aria-pressed={debug}
            onClick={() => setDebug((v) => !v)}
            className="ml-auto min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-xs dark:border-neutral-700"
          >
            Debug
          </button>
        </div>

        <form onSubmit={submit} className="flex gap-2">
          <input
            aria-label="Message"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={s.quiz?.phase === "asking" || s.quiz?.phase === "hint" ? "Type your answer…" : "Or type what you want to say…"}
            className="min-h-11 flex-1 rounded-lg border border-neutral-300 bg-transparent px-3 py-2 text-base dark:border-neutral-700"
          />
          <button
            type="submit"
            disabled={!ready}
            className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>

      <div className="flex flex-col gap-6">
        {s.explanation && (
          <ExplainCard
            key={s.explanation.id}
            explanation={s.explanation}
            track={TRACK}
            onSaved={() => {
              markSaved();
              void listNotes(TRACK).then(syncNotes);
            }}
          />
        )}
        <NotePane
          notes={s.notes}
          links={s.links}
          selectedId={selectedId}
          onSelect={setPicked}
          onUndo={onUndo}
          onConfirm={onConfirm}
        />
        <DiagramPane note={selectedNote} diagram={selectedDiagram} onDiagram={setDiagram} />
      </div>

      {debug && (
        <DebugOverlay
          latency={s.latency}
          connection={s.connection}
          micMode={micMode}
          audioInput={s.audioInput}
        />
      )}
    </main>
  );
}
