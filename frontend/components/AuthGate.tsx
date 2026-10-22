"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { AUTH_EVENT, getAuthStatus, logout as apiLogout } from "@/lib/http";

interface AuthCtx {
  authRequired: boolean;
  logout: () => Promise<void>;
  /** Re-read the session state (the login page calls this before navigating on). */
  recheck: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>({
  authRequired: false,
  logout: async () => undefined,
  recheck: async () => undefined,
});
export const useAuth = () => useContext(Ctx);

type State = "checking" | "ok" | "login";

/** Sends visitors without a valid session to /login, and back there if it expires mid-use. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [state, setState] = useState<State>("checking");
  const [authRequired, setAuthRequired] = useState(false);

  const check = useCallback(async () => {
    try {
      const s = await getAuthStatus();
      setAuthRequired(s.auth_required);
      setState(!s.auth_required || s.authenticated ? "ok" : "login");
    } catch {
      setState("ok"); // backend unreachable: let each page show its own error
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check, path]);

  useEffect(() => {
    const onExpired = () => setState("login");
    window.addEventListener(AUTH_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EVENT, onExpired);
  }, []);

  const onLoginPage = path === "/login";
  useEffect(() => {
    if (state === "login" && !onLoginPage) {
      router.replace(`/login?next=${encodeURIComponent(path)}`);
    }
  }, [state, onLoginPage, path, router]);

  const logout = useCallback(async () => {
    await apiLogout();
    setState("login");
    router.replace("/login");
  }, [router]);

  if (!onLoginPage && state !== "ok") return null;
  return <Ctx.Provider value={{ authRequired, logout, recheck: check }}>{children}</Ctx.Provider>;
}
