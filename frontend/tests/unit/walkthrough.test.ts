import { describe, expect, it } from "vitest";
import { cellsAt, parseWalkthrough, pointersByCell } from "@/lib/walkthrough";

const good = {
  array: ["1", "3", "5", "7"],
  steps: [
    { caption: "Start at both ends.", pointers: { left: 0, right: 3 }, highlight: [0, 3] },
    { caption: "Move left.", pointers: { left: 1, right: 3 } },
  ],
};

describe("parseWalkthrough", () => {
  it("reads a stored walkthrough", () => {
    const w = parseWalkthrough(JSON.stringify(good));
    expect(w?.steps).toHaveLength(2);
    expect(w?.steps[1].highlight).toEqual([]);
    expect(pointersByCell(w!.steps[0])).toEqual({ 0: ["left"], 3: ["right"] });
  });

  it.each([
    ["not JSON", "left 0, right 3"],
    ["one step", JSON.stringify({ ...good, steps: [good.steps[0]] })],
    ["pointer past the end", JSON.stringify({ ...good, steps: [good.steps[0], { caption: "x", pointers: { i: 4 } }] })],
    ["negative pointer", JSON.stringify({ ...good, steps: [good.steps[0], { caption: "x", pointers: { i: -1 } }] })],
    ["bad highlight", JSON.stringify({ ...good, steps: [good.steps[0], { caption: "x", highlight: [9] }] })],
    ["array changes length", JSON.stringify({ ...good, steps: [good.steps[0], { caption: "x", array: ["1"] }] })],
    ["missing caption", JSON.stringify({ ...good, steps: [good.steps[0], { pointers: {} }] })],
  ])("returns null for %s so the caller can fall back", (_, source) => {
    expect(parseWalkthrough(source)).toBeNull();
  });

  it("uses a step's own array when the values change", () => {
    const swapped = ["3", "1", "5", "7"];
    const w = parseWalkthrough(
      JSON.stringify({ ...good, steps: [good.steps[0], { caption: "swap", array: swapped }] }),
    )!;
    expect(cellsAt(w, 0)).toEqual(good.array);
    expect(cellsAt(w, 1)).toEqual(swapped);
  });
});
