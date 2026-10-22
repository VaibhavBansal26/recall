"use client";

import { useState } from "react";
import { cellsAt, pointersByCell, type Walkthrough } from "@/lib/walkthrough";

/** Array cells with named pointers, one step at a time. Keyboard: arrow keys move between steps. */
export function WalkthroughView({ walkthrough }: { walkthrough: Walkthrough }) {
  const [i, setI] = useState(0);
  const last = walkthrough.steps.length - 1;
  const step = walkthrough.steps[i];
  const cells = cellsAt(walkthrough, i);
  const pointers = pointersByCell(step);
  const go = (to: number) => setI(Math.min(last, Math.max(0, to)));

  return (
    <div
      data-testid="walkthrough"
      tabIndex={0}
      aria-label="Step by step walkthrough"
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") go(i + 1);
        if (e.key === "ArrowLeft") go(i - 1);
      }}
      className="flex flex-col gap-3 rounded-lg outline-offset-4"
    >
      <ol className="flex flex-wrap items-start gap-1.5" aria-label="Array">
        {cells.map((value, idx) => {
          const on = step.highlight.includes(idx);
          return (
            <li key={idx} className="flex w-11 flex-col items-center gap-1">
              <span
                data-testid="cell"
                data-highlight={on}
                className={`flex h-11 w-11 items-center justify-center rounded-lg border text-sm font-medium ${
                  on
                    ? "border-indigo-600 bg-indigo-50 text-indigo-900 dark:border-indigo-400 dark:bg-indigo-950/40 dark:text-indigo-100"
                    : "border-neutral-300 dark:border-neutral-700"
                }`}
              >
                {value}
              </span>
              <span className="font-mono text-[10px] opacity-50">{idx}</span>
              <span className="flex min-h-5 flex-col items-center text-xs font-semibold text-indigo-700 dark:text-indigo-300">
                {(pointers[idx] ?? []).map((name) => (
                  <span key={name} data-testid="pointer">
                    ↑ {name}
                  </span>
                ))}
              </span>
            </li>
          );
        })}
      </ol>
      <p aria-live="polite" data-testid="walkthrough-caption" className="min-h-10 text-sm">
        {step.caption}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => go(i - 1)}
          disabled={i === 0}
          className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm disabled:opacity-40 dark:border-neutral-700"
        >
          Back
        </button>
        <span className="text-xs opacity-70" data-testid="walkthrough-step">
          Step {i + 1} of {last + 1}
        </span>
        <button
          type="button"
          onClick={() => go(i + 1)}
          disabled={i === last}
          className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 text-sm disabled:opacity-40 dark:border-neutral-700"
        >
          Next
        </button>
      </div>
    </div>
  );
}
