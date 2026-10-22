"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { getDue, listSources } from "@/lib/api";
import { useRefreshOnFocus } from "@/lib/useRefreshOnFocus";
import { useTrack } from "@/lib/track";
import { useAuth } from "./AuthGate";
import { TrackSwitcher } from "./TrackSwitcher";

const LINKS = [
  { href: "/session", label: "Session" },
  { href: "/review", label: "Review" },
  { href: "/sources", label: "Sources" },
  { href: "/stats", label: "Stats" },
  { href: "/map", label: "Memory map" },
];

export function Nav() {
  const path = usePathname();
  const { authRequired, logout } = useAuth();
  const track = useTrack((t) => t.track);
  const [due, setDue] = useState<number | null>(null);
  const [awaiting, setAwaiting] = useState(0);
  const refresh = useCallback(
    () =>
      Promise.all([
        getDue(track).then((d) => setDue(d.total_due)),
        listSources().then((s) => setAwaiting(s.filter((x) => x.status === "ready").length)),
      ])
        .then(() => undefined)
        .catch(() => undefined),
    [track],
  );
  useEffect(() => {
    if (path !== "/login") void refresh();
  }, [path, refresh]);
  useRefreshOnFocus(refresh, 60_000);
  if (path === "/login") return null;
  return (
    <nav aria-label="Main" className="border-b border-neutral-200 dark:border-neutral-800">
      <ul className="mx-auto flex max-w-5xl gap-4 px-6 py-2 text-sm">
        {LINKS.map((l) => (
          <li key={l.href}>
            <Link
              href={l.href}
              aria-current={path.startsWith(l.href) ? "page" : undefined}
              className="py-1 aria-[current=page]:font-semibold aria-[current=page]:underline"
            >
              {l.label}
              {l.href === "/review" && due ? (
                <span
                  data-testid="due-badge"
                  className="ml-1 rounded-full bg-indigo-600 px-1.5 py-0.5 text-xs font-normal text-white"
                >
                  {due}
                </span>
              ) : null}
              {l.href === "/sources" && awaiting > 0 ? (
                <span
                  data-testid="sources-badge"
                  className="ml-1 rounded-full bg-amber-500 px-1.5 py-0.5 text-xs font-normal text-white"
                  title="Waiting for your approval"
                >
                  {awaiting}
                </span>
              ) : null}
            </Link>
          </li>
        ))}
        <li className="ml-auto">
          <TrackSwitcher />
        </li>
        {authRequired && (
          <li>
            <button type="button" onClick={() => void logout()} className="py-1 opacity-70">
              Sign out
            </button>
          </li>
        )}
      </ul>
    </nav>
  );
}
