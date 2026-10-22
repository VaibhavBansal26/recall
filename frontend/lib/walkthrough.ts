/** A step-by-step picture of an algorithm: array cells, named pointers and a caption per step. */

export interface WalkStep {
  caption: string;
  pointers: Record<string, number>;
  highlight: number[];
  array?: string[];
}

export interface Walkthrough {
  array: string[];
  steps: WalkStep[];
}

const isIndex = (v: unknown, n: number): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= 0 && v < n;

/** Parse the stored JSON; null when it is not a drawable walkthrough (the caller shows steps). */
export function parseWalkthrough(source: string): Walkthrough | null {
  let raw: unknown;
  try {
    raw = JSON.parse(source);
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null) return null;
  const { array, steps } = raw as { array?: unknown; steps?: unknown };
  if (!Array.isArray(array) || array.length < 2 || !Array.isArray(steps) || steps.length < 2) {
    return null;
  }
  const cells = array.map(String);
  const out: WalkStep[] = [];
  for (const s of steps as Record<string, unknown>[]) {
    if (typeof s !== "object" || s === null || typeof s.caption !== "string") return null;
    const pointers: Record<string, number> = {};
    for (const [name, at] of Object.entries((s.pointers as Record<string, unknown>) ?? {})) {
      if (!isIndex(at, cells.length)) return null;
      pointers[name] = at;
    }
    const highlight = Array.isArray(s.highlight) ? s.highlight : [];
    if (!highlight.every((h) => isIndex(h, cells.length))) return null;
    const own = Array.isArray(s.array) ? s.array.map(String) : undefined;
    if (own && own.length !== cells.length) return null;
    out.push({ caption: s.caption, pointers, highlight: highlight as number[], array: own });
  }
  return { array: cells, steps: out };
}

/** The pointer names sitting on each cell at a step, e.g. { 0: ["left"], 5: ["right"] }. */
export function pointersByCell(step: WalkStep): Record<number, string[]> {
  const byCell: Record<number, string[]> = {};
  for (const [name, at] of Object.entries(step.pointers)) (byCell[at] ??= []).push(name);
  return byCell;
}

export const cellsAt = (w: Walkthrough, i: number): string[] => w.steps[i].array ?? w.array;
