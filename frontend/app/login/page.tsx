"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { useAuth } from "@/components/AuthGate";
import { login } from "@/lib/http";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { recheck } = useAuth();
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const result = await login(passphrase);
    setBusy(false);
    if (result.ok) {
      // Update the gate first, or it would still think we are signed out and bounce us back.
      await recheck();
      const next = params.get("next");
      // Only follow same-site paths so a crafted link cannot redirect elsewhere.
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/session");
    } else {
      setError(result.error);
    }
  }

  return (
    <main className="mx-auto flex min-h-[80dvh] max-w-sm flex-col justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">Recall</h1>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Passphrase
          <input
            type="password"
            name="passphrase"
            autoComplete="current-password"
            autoFocus
            value={passphrase}
            onChange={(e) => setPassphrase(e.target.value)}
            className="rounded-lg border border-neutral-300 bg-transparent px-3 py-2 text-base dark:border-neutral-700"
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !passphrase}
          className="rounded-lg bg-indigo-600 px-4 py-3 text-base text-white disabled:opacity-40"
        >
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
