export type OrbState = "idle" | "listening" | "thinking" | "speaking";

const STYLE: Record<OrbState, { ring: string; core: string; label: string }> = {
  idle: { ring: "", core: "bg-neutral-300 dark:bg-neutral-700", label: "Idle" },
  listening: {
    ring: "motion-safe:animate-ping bg-emerald-400/40",
    core: "bg-emerald-500",
    label: "Listening",
  },
  thinking: {
    ring: "",
    core: "bg-amber-400 motion-safe:animate-pulse",
    label: "Thinking",
  },
  speaking: {
    ring: "motion-safe:animate-ping bg-indigo-400/40",
    core: "bg-indigo-500",
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
      <div className="relative h-16 w-16">
        {s.ring && <span className={`absolute inset-0 rounded-full ${s.ring}`} />}
        <span className={`absolute inset-2 rounded-full transition-colors ${s.core}`} />
      </div>
      <span className="text-xs opacity-70">{s.label}</span>
    </div>
  );
}
