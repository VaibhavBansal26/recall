import { describe, expect, it } from "vitest";
import { forceLayout, strengthColor } from "@/lib/layout";

const ids = ["a", "b", "c", "d", "e"];
const edges = [
  { source: "a", target: "b" },
  { source: "b", target: "c" },
  { source: "d", target: "e" },
];

describe("forceLayout", () => {
  it("places every node, finitely", () => {
    const pos = forceLayout(ids, edges);
    expect(Object.keys(pos).sort()).toEqual(ids);
    for (const p of Object.values(pos)) {
      expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
    }
  });

  it("is deterministic", () => {
    expect(forceLayout(ids, edges)).toEqual(forceLayout(ids, edges));
  });

  it("keeps nodes apart and pulls linked nodes closer than unlinked ones", () => {
    const pos = forceLayout(ids, edges);
    const dist = (a: string, b: string) => Math.hypot(pos[a].x - pos[b].x, pos[a].y - pos[b].y);
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) expect(dist(ids[i], ids[j])).toBeGreaterThan(20);
    }
    expect(dist("a", "b")).toBeLessThan(dist("a", "e"));
  });

  it("keeps unlinked notes inside the frame instead of flinging them away", () => {
    const pos = forceLayout(["a", "b", "c", "d"], [{ source: "a", target: "b" }]);
    for (const p of Object.values(pos)) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(900);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(600);
    }
  });

  it("handles empty, single and self-linked graphs and ignores unknown edge endpoints", () => {
    expect(forceLayout([], [])).toEqual({});
    expect(Object.keys(forceLayout(["x"], []))).toEqual(["x"]);
    const pos = forceLayout(["x", "y"], [
      { source: "x", target: "x" },
      { source: "x", target: "ghost" },
    ]);
    expect(Object.keys(pos).sort()).toEqual(["x", "y"]);
  });
});

describe("strengthColor", () => {
  it("is neutral without review history and red to green otherwise", () => {
    expect(strengthColor(null)).toContain("220 10%");
    expect(strengthColor(0)).toContain("hsl(0 ");
    expect(strengthColor(1)).toContain("hsl(120 ");
    expect(strengthColor(5)).toBe(strengthColor(1));
  });
});
