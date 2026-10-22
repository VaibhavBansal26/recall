// Empty NEXT_PUBLIC_API_URL means "same origin" (production behind Caddy); the dev stack talks
// to the backend directly on :8000 and relies on CORS with credentials.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const AUTH_EVENT = "recall:unauthorized";

export function wsUrl(
  apiUrl: string = API_URL,
  loc: { protocol: string; host: string } = window.location,
): string {
  if (apiUrl === "") {
    return `${loc.protocol === "https:" ? "wss" : "ws"}://${loc.host}/ws/voice`;
  }
  return `${apiUrl.replace(/^http/, "ws")}/ws/voice`;
}

/** fetch() against the API: sends the session cookie and tells the app when it has expired. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_URL}${path}`, { ...init, credentials: "include" });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    window.dispatchEvent(new Event(AUTH_EVENT));
  }
  return res;
}

export interface AuthStatus {
  auth_required: boolean;
  authenticated: boolean;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const res = await apiFetch("/api/auth/me");
  if (!res.ok) throw new Error(`auth status failed: ${res.status}`);
  return (await res.json()) as AuthStatus;
}

export async function login(passphrase: string): Promise<{ ok: true } | { ok: false; error: string }> {
  const res = await apiFetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ passphrase }),
  });
  if (res.ok) return { ok: true };
  if (res.status === 429) {
    const wait = Number(res.headers.get("Retry-After") ?? 0);
    const mins = Math.max(1, Math.ceil(wait / 60));
    return { ok: false, error: `Too many attempts. Try again in about ${mins} min.` };
  }
  if (res.status === 401) return { ok: false, error: "That passphrase is not right." };
  return { ok: false, error: "Could not reach the server." };
}

export async function logout(): Promise<void> {
  await apiFetch("/api/auth/logout", { method: "POST" });
}
