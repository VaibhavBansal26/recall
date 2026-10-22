import type { ReadBackView } from "@/lib/events";

interface Props {
  readBack: ReadBackView;
  onCommand: (word: string) => void;
}

const COMMANDS = ["slower", "repeat", "next", "faster", "stop"];

export function ReadBackBar({ readBack, onCommand }: Props) {
  return (
    <section
      aria-label="Read back"
      data-testid="readback"
      className="flex flex-col gap-2 rounded-xl border border-neutral-200 p-3 text-sm dark:border-neutral-800"
    >
      <p>
        Reading note {readBack.index + 1} of {readBack.total}
        {readBack.title ? `: ${readBack.title}` : ""}
        <span className="ml-2 opacity-60">speed {readBack.speed.toFixed(2)}×</span>
      </p>
      <div className="flex flex-wrap gap-2">
        {COMMANDS.map((word) => (
          <button
            key={word}
            type="button"
            onClick={() => onCommand(word)}
            className="min-h-11 rounded-lg border border-neutral-300 px-3 py-2 capitalize dark:border-neutral-700"
          >
            {word}
          </button>
        ))}
      </div>
    </section>
  );
}
