export interface Pos {
  x: number;
  y: number;
}

interface Options {
  width?: number;
  height?: number;
  iterations?: number;
}

/**
 * Small deterministic force-directed layout (Fruchterman-Reingold). Nodes start on a circle in the
 * given order, so the same graph always lays out the same way between renders.
 */
export function forceLayout(
  ids: string[],
  edges: { source: string; target: string }[],
  { width: baseWidth = 900, height: baseHeight = 600, iterations = 120 }: Options = {},
): Record<string, Pos> {
  const n = ids.length;
  // Grow the frame with the node count so large maps are not packed onto the edges.
  const grow = Math.max(1, Math.sqrt(n / 8));
  const width = baseWidth * grow;
  const height = baseHeight * grow;
  const margin = 60;
  const pos: Record<string, Pos> = {};
  if (n === 0) return pos;
  const radius = Math.min(width, height) / 2.5;
  ids.forEach((id, i) => {
    const a = (2 * Math.PI * i) / n;
    pos[id] = { x: width / 2 + radius * Math.cos(a), y: height / 2 + radius * Math.sin(a) };
  });
  if (n === 1) return pos;

  const k = Math.sqrt((width * height) / n) * 0.75;
  const valid = edges.filter((e) => pos[e.source] && pos[e.target] && e.source !== e.target);
  let temp = width / 8;
  for (let it = 0; it < iterations; it++) {
    const disp: Record<string, Pos> = Object.fromEntries(ids.map((id) => [id, { x: 0, y: 0 }]));
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = ids[i];
        const b = ids[j];
        let dx = pos[a].x - pos[b].x;
        let dy = pos[a].y - pos[b].y;
        let d = Math.hypot(dx, dy);
        if (d < 0.01) {
          dx = 0.01 * (i + 1);
          dy = 0.01 * (j + 1);
          d = Math.hypot(dx, dy);
        }
        const f = (k * k) / d;
        disp[a].x += (dx / d) * f;
        disp[a].y += (dy / d) * f;
        disp[b].x -= (dx / d) * f;
        disp[b].y -= (dy / d) * f;
      }
    }
    for (const e of valid) {
      const dx = pos[e.source].x - pos[e.target].x;
      const dy = pos[e.source].y - pos[e.target].y;
      const d = Math.max(Math.hypot(dx, dy), 0.01);
      const f = (d * d) / k;
      disp[e.source].x -= (dx / d) * f;
      disp[e.source].y -= (dy / d) * f;
      disp[e.target].x += (dx / d) * f;
      disp[e.target].y += (dy / d) * f;
    }
    for (const id of ids) {
      // Weak pull to the centre so unlinked notes drift in instead of being repelled away.
      disp[id].x += (width / 2 - pos[id].x) * 0.05;
      disp[id].y += (height / 2 - pos[id].y) * 0.05;
      const d = Math.max(Math.hypot(disp[id].x, disp[id].y), 0.01);
      const step = Math.min(d, temp);
      pos[id].x = clamp(pos[id].x + (disp[id].x / d) * step, margin, width - margin);
      pos[id].y = clamp(pos[id].y + (disp[id].y / d) * step, margin, height - margin);
    }
    temp *= 0.96;
  }
  return pos;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** Red (forgotten) to green (strong). Null strength = no review history yet. */
export function strengthColor(strength: number | null): string {
  if (strength === null) return "hsl(220 10% 88%)";
  const s = Math.max(0, Math.min(1, strength));
  return `hsl(${Math.round(s * 120)} 65% 82%)`;
}
