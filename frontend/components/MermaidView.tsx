"use client";

import { useEffect, useState } from "react";

/** Parses first, so a bad diagram shows the parser message and the source instead of a bomb icon. */
export function MermaidView({ source }: { source: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: dark ? "dark" : "default",
        });
        await mermaid.parse(source);
        const { svg: rendered } = await mermaid.render(
          `m${Math.random().toString(36).slice(2)}`,
          source,
        );
        if (!cancelled) {
          setSvg(rendered);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setSvg(null);
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source]);

  if (error) {
    return (
      <div role="alert" className="text-xs">
        <p className="text-red-600 dark:text-red-400">Could not render this diagram.</p>
        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap opacity-70">{source}</pre>
      </div>
    );
  }
  if (!svg) return <p className="text-xs opacity-60">Drawing…</p>;
  return (
    <div
      data-testid="mermaid-svg"
      className="overflow-x-auto [&_svg]:h-auto [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
