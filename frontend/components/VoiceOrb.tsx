export type OrbState = "idle" | "listening" | "thinking" | "speaking";

const STYLE: Record<OrbState, { ring: string; core: string; label: string }> = {
  idle: { ring: "", core: "ring-neutral-300 dark:ring-neutral-700", label: "Idle" },
  listening: {
    ring: "motion-safe:animate-ping bg-emerald-400/40",
    core: "ring-emerald-500",
    label: "Listening",
  },
  thinking: {
    ring: "",
    core: "ring-amber-400 motion-safe:animate-pulse",
    label: "Thinking",
  },
  speaking: {
    ring: "motion-safe:animate-ping bg-indigo-400/40",
    core: "ring-indigo-500",
    label: "Speaking",
  },
};

export function VoiceOrb({ state }: { state: OrbState }) {
  const s = STYLE[state];
  return (
    <div
      role="status"
      aria-label={`Voice: ${s.label}`}
      data-testid="orb"
      data-state={state}
      className="flex flex-col items-center gap-2"
    >
      <div className="relative h-24 w-24">
        {s.ring && <span className={`absolute -inset-1 rounded-full ${s.ring}`} />}
        {/* The face stays put; the ring colour carries the state (green listening, amber thinking, indigo speaking). */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/avatar.webp"
          alt=""
          width={96}
          height={96}
          className={`absolute inset-0 h-24 w-24 rounded-full object-cover ring-4 transition-colors ${s.core}`}
        />
      </div>
      <span className="text-xs opacity-70">
        <strong className="font-medium">Aria</strong> · {s.label}
      </span>
    </div>
  );
}
