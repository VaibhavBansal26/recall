/** Pure helpers for the stats screen. */

export const pct = (v: number | null | undefined): string =>
  v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`;

export interface CurvePoint {
  date: string;
  reviews: number;
  recalled: number;
  retention?: number | null;
}

export interface Geometry {
  /** Points that have data, in pixel space. */
  points: { x: number; y: number; src: CurvePoint; index: number }[];
  /** SVG path for the line, broken into separate runs across days with no reviews. */
  line: string;
  /** Closed path for the soft area wash under the line. */
  area: string;
  xTicks: { x: number; label: string }[];
  yTicks: { y: number; label: string }[];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function shortDate(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}

/**
 * Lay a retention series out in a width x height box (0 to 100% on y). Days without reviews are
 * gaps, not zeros: a missing day is not a failed day.
 */
export function layoutCurve(
  series: CurvePoint[],
  width: number,
  height: number,
  pad = { left: 36, right: 40, top: 12, bottom: 24 },
): Geometry {
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const x = (i: number) => pad.left + (series.length <= 1 ? 0 : (i / (series.length - 1)) * innerW);
  const y = (v: number) => pad.top + (1 - v) * innerH;

  const points = series
    .map((src, index) => ({ src, index }))
    .filter((p): p is { src: CurvePoint & { retention: number }; index: number } => p.src.retention != null)
    .map((p) => ({ x: x(p.index), y: y(p.src.retention), src: p.src, index: p.index }));

  let line = "";
  let area = "";
  let prev: number | null = null;
  let runStart: (typeof points)[number] | null = null;
  let runEnd: (typeof points)[number] | null = null;
  const closeRun = () => {
    if (runStart && runEnd && runEnd !== runStart) {
      area += `L${runEnd.x.toFixed(1)},${y(0)}L${runStart.x.toFixed(1)},${y(0)}Z`;
    }
  };
  for (const p of points) {
    const adjacent = prev !== null && p.index - prev === 1;
    if (adjacent) {
      line += `L${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      area += `L${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    } else {
      closeRun();
      line += `${line ? " " : ""}M${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      area += `${area ? " " : ""}M${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      runStart = p;
    }
    runEnd = p;
    prev = p.index;
  }
  closeRun();

  const step = series.length > 14 ? 7 : 2;
  const xTicks = series
    .map((s, i) => ({ s, i }))
    .filter(({ i }) => (series.length - 1 - i) % step === 0)
    .map(({ s, i }) => ({ x: x(i), label: shortDate(s.date) }));
  const yTicks = [0, 0.5, 1].map((v) => ({ y: y(v), label: `${Math.round(v * 100)}%` }));
  return { points, line, area, xTicks, yTicks };
}

/** The data point nearest a horizontal pixel position, or null when there are none. */
export function nearestPoint(g: Geometry, px: number): Geometry["points"][number] | null {
  let best: Geometry["points"][number] | null = null;
  for (const p of g.points) {
    if (best === null || Math.abs(p.x - px) < Math.abs(best.x - px)) best = p;
  }
  return best;
}
