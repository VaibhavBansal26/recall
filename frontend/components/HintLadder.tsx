"use client";

import type { QuizResult, QuizView } from "@/lib/events";

type Action = "hint" | "forgot" | "skip" | "end";

interface Props {
  quiz: QuizView | null;
  results: QuizResult[];
  dueCount: number | null;
  ready: boolean;
  onStart: () => void;
  onAction: (action: Action) => void;
}

const STEPS = ["Ask", "Nudge", "Partial", "Reveal"];

function formatDue(iso: string | null): string {
  if (!iso) return "";
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (mins < 2) return "in a minute or two";
  if (mins < 90) return `in ${mins} minutes`;
  if (mins < 36 * 60) return `in about ${Math.round(mins / 60)} hours`;
  return `in about ${Math.round(mins / 1440)} days`;
}

function gradeLabel(tier: number, grade: string | null): string {
  if (!grade) return "";
  const how = tier === 0 ? "no hint" : tier === 3 ? "full reveal" : `tier ${tier} hint`;
  return `${grade} (${how})`;
}

export function HintLadder({ quiz, results, dueCount, ready, onStart, onAction }: Props) {
  const active = quiz && (quiz.phase === "asking" || quiz.phase === "hint" || quiz.phase === "graded");
  const ended = quiz?.phase === "ended";

  return (
    <section aria-label="Quiz" className="flex flex-col gap-3 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide opacity-60">Recall</h2>
        {!active && (
          <button
            type="button"
            disabled={!ready}
            onClick={onStart}
            className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {ended ? "Quiz again" : "Quiz me"}
            {dueCount !== null && dueCount > 0 ? ` (${dueCount} due)` : ""}
          </button>
        )}
      </div>

      {quiz?.phase === "empty" && (
        <p data-testid="quiz-empty" className="text-sm opacity-80">
          Nothing is due right now.
          {quiz.nextDue ? ` Your next review is ${formatDue(quiz.nextDue)}.` : " Capture some ideas first."}
        </p>
      )}

      {!quiz && (
        <p className="text-sm opacity-70">
          {dueCount === 0
            ? "Nothing is due right now."
            : "Questions come from what is due, not at random. Say “quiz me” or press the button."}
        </p>
      )}

      {active && quiz && (
        <>
          <p className="text-xs opacity-60">
            Question {quiz.position} of {quiz.total}
            {quiz.noteTitle ? ` · ${quiz.noteTitle}` : ""}
          </p>
          <p data-testid="quiz-prompt" className="text-lg font-medium">
            {quiz.prompt}
          </p>

          <ol aria-label="Hint ladder" className="flex gap-1 text-xs" data-testid="ladder">
            {STEPS.map((label, i) => (
              <li
                key={label}
                aria-current={i === quiz.tier && quiz.phase !== "graded" ? "step" : undefined}
                className={`flex-1 rounded px-2 py-1 text-center ${
                  i < quiz.tier
                    ? "bg-indigo-100 text-indigo-900 dark:bg-indigo-900/40 dark:text-indigo-200"
                    : i === quiz.tier
                      ? "bg-indigo-600 text-white"
                      : "bg-neutral-100 opacity-60 dark:bg-neutral-800"
                }`}
              >
                {label}
              </li>
            ))}
          </ol>

          {quiz.hint && quiz.phase === "hint" && (
            <p data-testid="quiz-hint" className="rounded-lg bg-neutral-100 p-3 text-sm dark:bg-neutral-800">
              {quiz.hint}
            </p>
          )}
          {quiz.answer && (
            <p data-testid="quiz-answer" className="text-sm">
              <span className="opacity-60">Answer: </span>
              {quiz.answer}
            </p>
          )}

          {quiz.phase === "graded" ? (
            <div data-testid="quiz-graded" className="text-sm">
              <span className="rounded bg-emerald-100 px-2 py-0.5 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200">
                {gradeLabel(quiz.tier, quiz.grade)}
              </span>
              {quiz.fragile && (
                <span className="ml-2 text-red-600 dark:text-red-400">
                  ⚠ Fragile: I will bring it back sooner.
                </span>
              )}
              <span className="ml-2 opacity-60">Next {formatDue(quiz.nextDue)}.</span>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={quiz.tier >= 3}
                onClick={() => onAction("hint")}
                className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm disabled:opacity-40 dark:border-neutral-700"
              >
                Give me a hint
              </button>
              <button
                type="button"
                onClick={() => onAction("forgot")}
                className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700"
              >
                I forgot
              </button>
              <button
                type="button"
                onClick={() => onAction("skip")}
                className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700"
              >
                Skip
              </button>
              <button
                type="button"
                onClick={() => onAction("end")}
                className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700"
              >
                End quiz
              </button>
            </div>
          )}
        </>
      )}

      {ended && quiz?.summary && (
        <div data-testid="quiz-summary" className="text-sm">
          <p className="font-medium">
            {quiz.summary.unaided} of {quiz.summary.total} without a hint
          </p>
          <p className="opacity-70">
            {quiz.summary.hinted} with a hint · {quiz.summary.revealed} revealed
            {quiz.summary.fragile > 0 ? ` · ${quiz.summary.fragile} marked fragile` : ""}
          </p>
        </div>
      )}

      {results.length > 0 && (
        <ul aria-label="Grades" className="flex flex-col gap-1 text-xs opacity-80">
          {results.map((r, i) => (
            <li key={`${r.itemId}-${i}`}>
              <span className="font-medium">{r.grade}</span> · {r.prompt}
              {r.fragile ? " ⚠" : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
