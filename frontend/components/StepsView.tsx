/** Plain step diagram: the fallback when Mermaid could not be produced or parsed. */
export function StepsView({ source }: { source: string }) {
  const steps = source.split("\n").filter((s) => s.trim());
  return (
    <ol data-testid="steps" className="flex flex-col items-stretch gap-1 text-sm">
      {steps.map((step, i) => (
        <li key={i} className="flex flex-col items-center">
          <div className="w-full rounded-lg border border-neutral-300 px-3 py-2 dark:border-neutral-700">
            <span className="mr-2 font-mono text-xs opacity-60">{i + 1}</span>
            {step}
          </div>
          {i < steps.length - 1 && <span aria-hidden="true" className="opacity-50">↓</span>}
        </li>
      ))}
    </ol>
  );
}
