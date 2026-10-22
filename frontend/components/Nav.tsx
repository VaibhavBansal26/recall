"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "./AuthGate";

const LINKS = [
  { href: "/session", label: "Session" },
  { href: "/map", label: "Memory map" },
];

export function Nav() {
  const path = usePathname();
  const { authRequired, logout } = useAuth();
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
            </Link>
          </li>
        ))}
        {authRequired && (
          <li className="ml-auto">
            <button type="button" onClick={() => void logout()} className="py-1 opacity-70">
              Sign out
            </button>
          </li>
        )}
      </ul>
    </nav>
  );
}
