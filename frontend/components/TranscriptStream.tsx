import type { StoredUtterance } from "@/lib/events";

interface Props {
  utterances: StoredUtterance[];
  partial: string;
  assistantDraft: string;
}

export function TranscriptStream({ utterances, partial, assistantDraft }: Props) {
  return (
    <ul aria-label="Transcript" className="flex flex-col gap-3">
      {utterances.map((u) => (
        <li
          key={u.id}
          className={
            u.speaker === "user"
              ? "self-end max-w-[85%] rounded-2xl bg-indigo-600 px-4 py-2 text-white"
              : "self-start max-w-[85%] rounded-2xl bg-neutral-100 px-4 py-2 dark:bg-neutral-800"
          }
        >
          <span className="sr-only">{u.speaker === "user" ? "You: " : "Recall: "}</span>
          {u.text}
          {u.interrupted && <span className="ml-1 text-xs italic opacity-60">(interrupted)</span>}
        </li>
      ))}
      {partial && (
        <li
          data-testid="partial"
          className="self-end max-w-[85%] rounded-2xl border border-dashed border-indigo-400 px-4 py-2 italic opacity-80"
        >
          {partial}
        </li>
      )}
      {assistantDraft && (
        <li className="self-start max-w-[85%] rounded-2xl bg-neutral-100 px-4 py-2 italic opacity-70 dark:bg-neutral-800">
          {assistantDraft}
        </li>
      )}
    </ul>
  );
}
