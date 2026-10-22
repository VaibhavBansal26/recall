"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { getReadyBrief, type BriefOut } from "@/lib/api";
import { useRefreshOnFocus } from "@/lib/useRefreshOnFocus";

/**
 * "Your brief is ready": shown once the morning cron has built today's brief. It only offers; the
 * brief starts on a click, because browsers block audio that starts by itself.
 */
export function BriefBanner() {
  const router = useRouter();
  const path = usePathname();
  const [brief, setBrief] = useState<BriefOut | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      getReadyBrief()
        .then(setBrief)
        .catch(() => undefined),
    [],
  );
  // Re-check on every navigation, so it is gone as soon as the brief has been started.
  useEffect(() => {
    void refresh();
  }, [refresh, path]);
  useRefreshOnFocus(refresh, 60_000);

  if (!brief || dismissed === brief.id || path.startsWith("/review") || path === "/login") {
    return null;
  }
  const n = brief.questions.length;
  return (
    <div
      role="status"
      data-testid="brief-banner"
      className="border-b border-indigo-200 bg-indigo-50 dark:border-indigo-900 dark:bg-indigo-950/40"
    >
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-6 py-2 text-sm">
        <span>
          <strong>Your brief is ready.</strong> {n} question{n === 1 ? "" : "s"} on what&apos;s
          slipping{brief.due_today > 0 ? `, ${brief.due_today} due today` : ""}. About{" "}
          {Math.max(2, n)} minutes.
        </span>
        <button
          type="button"
          onClick={() => router.push(`/review?brief=${brief.id}`)}
          className="min-h-11 rounded-lg bg-indigo-600 px-4 py-2 text-white"
        >
          Start brief
        </button>
        <button
          type="button"
          onClick={() => setDismissed(brief.id)}
          className="min-h-11 rounded-lg px-3 py-2 opacity-70"
        >
          Later
        </button>
      </div>
    </div>
  );
}
