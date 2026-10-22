import { useEffect, useRef } from "react";

/**
 * Re-run `refresh` when the tab/app comes back to the foreground and every `intervalMs` while
 * visible. This is how a device picks up notes captured on another device.
 */
export function useRefreshOnFocus(refresh: () => void | Promise<void>, intervalMs = 30_000): void {
  const latest = useRef(refresh);
  latest.current = refresh;

  useEffect(() => {
    const run = () => {
      if (document.visibilityState === "visible") void latest.current();
    };
    document.addEventListener("visibilitychange", run);
    window.addEventListener("focus", run);
    const timer = window.setInterval(run, intervalMs);
    return () => {
      document.removeEventListener("visibilitychange", run);
      window.removeEventListener("focus", run);
      window.clearInterval(timer);
    };
  }, [intervalMs]);
}
