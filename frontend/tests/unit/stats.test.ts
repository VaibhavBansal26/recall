import { describe, expect, it } from "vitest";
import { layoutCurve, layoutTrend, nearestPoint, pct, shortDate, type CurvePoint } from "@/lib/stats";

const day = (n: number, reviews = 0, recalled = 0): CurvePoint => ({
  date: `2030-06-${String(n).padStart(2, "0")}`,
  reviews,
  recalled,
  retention: reviews ? recalled / reviews : null,
});

describe("formatting", () => {
  it("formats percentages and dates", () => {
    expect(pct(0.856)).toBe("86%");
    expect(pct(0)).toBe("0%");
    expect(pct(null)).toBe("–");
    expect(shortDate("2030-06-09")).toBe("Jun 9");
  });
});

describe("layoutCurve", () => {
  const series = [day(1, 4, 2), day(2, 4, 4), day(3), day(4, 2, 1), day(5, 5, 5)];

  it("plots only days with reviews and keeps retention within the box", () => {
    const g = layoutCurve(series, 640, 220);
    expect(g.points.map((p) => p.index)).toEqual([0, 1, 3, 4]);
    for (const p of g.points) {
      expect(p.y).toBeGreaterThanOrEqual(12);
      expect(p.y).toBeLessThanOrEqual(220 - 24);
    }
    expect(g.points[0].y).toBeGreaterThan(g.points[1].y); // 50% sits below 100%
  });

  it("breaks the line across a day with no reviews instead of drawing it down to zero", () => {
    const g = layoutCurve(series, 640, 220);
    expect(g.line.match(/M/g)).toHaveLength(2); // two runs: days 1-2 and days 4-5
    expect(g.line).not.toContain("NaN");
  });

  it("has labelled 0, 50 and 100 percent ticks and date ticks", () => {
    const g = layoutCurve(series, 640, 220);
    expect(g.yTicks.map((t) => t.label)).toEqual(["0%", "50%", "100%"]);
    expect(g.xTicks.at(-1)?.label).toBe("Jun 5");
  });

  it("copes with no data and a single point", () => {
    expect(layoutCurve([day(1), day(2)], 640, 220).points).toEqual([]);
    const one = layoutCurve([day(1, 3, 3)], 640, 220);
    expect(one.points).toHaveLength(1);
    expect(one.line).not.toContain("NaN");
  });

  it("finds the data point nearest the pointer", () => {
    const g = layoutCurve(series, 640, 220);
    const hit = nearestPoint(g, g.points[2].x + 3);
    expect(hit?.index).toBe(3);
    expect(nearestPoint(layoutCurve([day(1)], 640, 220), 100)).toBeNull();
  });
});

describe("layoutTrend", () => {
  const series = [
    { date: "2026-10-01", value: 40 },
    { date: "2026-10-02", value: 60 },
    { date: "2026-10-03", value: 80 },
  ];

  it("puts higher values higher up and spaces points evenly", () => {
    const g = layoutTrend(series, 300, 90);
    expect(g.points[2].y).toBeLessThan(g.points[0].y);
    expect(g.points[1].x - g.points[0].x).toBeCloseTo(g.points[2].x - g.points[1].x);
    expect(g.line.startsWith("M")).toBe(true);
  });

  it("keeps a flat or single-point series inside the box", () => {
    for (const s of [[series[0]], [series[0], { ...series[0], date: "2026-10-02" }]]) {
      const g = layoutTrend(s, 300, 90);
      for (const p of g.points) {
        expect(p.y).toBeGreaterThanOrEqual(0);
        expect(p.y).toBeLessThanOrEqual(90);
      }
    }
  });

  it("uses a fixed domain when given", () => {
    const g = layoutTrend(series, 300, 90, undefined, [0, 100]);
    expect(g.min).toBe(0);
    expect(g.max).toBe(100);
  });
});
