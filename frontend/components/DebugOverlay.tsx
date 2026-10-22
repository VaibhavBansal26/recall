import type { Latency } from "@/lib/events";

interface Props {
  latency: Latency | null;
  connection: string;
  micMode: string;
  audioInput: boolean;
}

const fmt = (ms: number | null) => (ms === null ? "n/a" : `${Math.round(ms)} ms`);

export function DebugOverlay({ latency, connection, micMode, audioInput }: Props) {
  return (
    <aside
      aria-label="Debug"
      className="rounded-lg md:fixed md:bottom-3 md:right-3 border border-neutral-300 bg-white/90 p-3 font-mono text-xs shadow dark:border-neutral-700 dark:bg-neutral-900/90"
    >
      <div className="mb-1 font-semibold">Last turn</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-3">
        <dt>speech end → 1st token</dt>
        <dd data-testid="lat-token">{fmt(latency?.sttToFirstTokenMs ?? null)}</dd>
        <dt>1st token → 1st audio</dt>
        <dd>{fmt(latency?.firstTokenToAudioMs ?? null)}</dd>
        <dt>speech end → 1st audio</dt>
        <dd data-testid="lat-audio">{fmt(latency?.sttToFirstAudioMs ?? null)}</dd>
      </dl>
      <div className="mt-2 opacity-70">
        ws {connection} · mic {micMode} · voice {audioInput ? "on" : "typed only"}
      </div>
      <div className="opacity-70">target: under 800 ms to first audio</div>
    </aside>
  );
}
