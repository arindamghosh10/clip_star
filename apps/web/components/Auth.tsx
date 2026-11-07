"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { SIGNED_OUT_EVENT, api, type AuthState, type Role } from "@/lib/api";
import { Button } from "./ui";

type Ctx = { state: AuthState | null; refresh: () => Promise<AuthState | null>; can: (what: Role) => boolean };
const AuthCtx = createContext<Ctx>({ state: null, refresh: async () => null, can: () => true });

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, editor: 2, owner: 3 };

/** Pages shown without the app frame and without being signed in. */
export const BARE = ["/login", "/setup", "/invite"];

export function useAuth() {
  return useContext(AuthCtx);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const path = usePathname();
  const router = useRouter();

  const refresh = useCallback(async () => {
    try {
      // links from push notifications and emails carry ?ws=<id>: open them in that workspace
      const wanted = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("ws") : null;
      if (wanted) {
        const url = new URL(window.location.href);
        url.searchParams.delete("ws");
        window.history.replaceState(null, "", url.toString());
        await api.switchWorkspace(wanted).catch(() => undefined);
      }
      const s = await api.authState();
      setState(s);
      setError(null);
      return s;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
    const onOut = () => refresh();
    window.addEventListener(SIGNED_OUT_EVENT, onOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onOut);
  }, [refresh]);

  const bare = BARE.some((p) => path.startsWith(p));
  useEffect(() => {
    if (!state) return;
    if (state.setup_required && !path.startsWith("/setup")) router.replace("/setup");
    else if (!state.setup_required && !state.user && !bare) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [state, path, bare, router]);

  // Open mode (first run) has no person yet: allow everything so the wizard works.
  const can = (what: Role) => !state?.user || RANK[state.user.role] >= RANK[what];

  if (error && !state) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="flex max-w-sm flex-col gap-3 rounded-md border border-line bg-surface p-6 text-sm">
          <p className="font-semibold">Can&apos;t reach the clip_star server</p>
          <p className="text-muted">{error}</p>
          <Button onClick={() => refresh()}>Try again</Button>
        </div>
      </div>
    );
  }
  const ready = state && (bare || state.user || state.setup_required);
  return <AuthCtx.Provider value={{ state, refresh, can }}>{ready ? children : <p className="p-8 text-sm text-muted">Loading…</p>}</AuthCtx.Provider>;
}
