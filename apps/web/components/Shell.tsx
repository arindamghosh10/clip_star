"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  Activity,
  BarChart3,
  Blocks,
  CalendarDays,
  Film,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Scissors,
  Rows3,
  Send,
  Settings,
  Users,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { StoreProvider, useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";
import { AuthProvider, BARE, useAuth } from "./Auth";
import { NotificationsBell } from "./Notifications";
import { cx } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/videos", label: "Videos", icon: Film },
  { href: "/clips", label: "Clips", icon: Scissors },
  { href: "/publishing", label: "Publishing", icon: Send },
  { href: "/posts", label: "Posts", icon: Rows3 },
  { href: "/calendar", label: "Calendar", icon: CalendarDays },
  { href: "/accounts", label: "Accounts", icon: Users },
  { href: "/engage", label: "Engage", icon: MessageSquare },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/engines", label: "Engines & connectors", icon: Blocks },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
];

function useNavCounts() {
  const summary = usePoll(api.commentSummary, { intervalMs: 20000 });
  // Clips is live: count real clips waiting for approval (no badge if the API is unreachable).
  const pending = usePoll(() => api.clips({ status: "pending" }), { intervalMs: 15000 });
  const awaiting = usePoll(api.batches, { intervalMs: 15000 });
  return {
    "/clips": pending.data?.length ?? 0,
    "/publishing": awaiting.data?.filter((b) => b.status === "awaiting").length ?? 0,
    "/engage": Object.entries(summary.data?.open ?? {}).reduce((n, [k, v]) => (k === "spam" ? n : n + (v ?? 0)), 0),
  } as Record<string, number>;
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const counts = useNavCounts();
  return (
    <nav className="flex flex-col gap-0.5" aria-label="Main">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        const n = counts[href];
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cx(
              "flex items-center gap-2.5 rounded px-2.5 py-2 text-sm font-medium transition-colors",
              active ? "bg-accent-soft text-accent" : "text-muted hover:bg-paper hover:text-ink",
            )}
          >
            <Icon size={16} aria-hidden />
            <span className="flex-1">{label}</span>
            {n ? <span className="rounded-full bg-gate-soft px-1.5 font-mono text-[11px] text-gate">{n}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 px-2.5">
      <span className="h-2.5 w-2.5 rounded-full bg-rec" aria-hidden />
      <span className="text-lg font-extrabold tracking-tight">clip_star</span>
    </Link>
  );
}

const ROLE_LABEL = { owner: "Owner", editor: "Editor", reviewer: "Reviewer", viewer: "Viewer" } as const;

function Workspace() {
  const ws = usePoll(api.workspace, { intervalMs: 60000 });
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  const { state, refresh } = useAuth();
  const router = useRouter();
  const user = state?.user;
  async function signOut() {
    await api.logout().catch(() => undefined);
    await refresh();
    router.replace("/login");
  }
  return (
    <div className="flex flex-col gap-2">
      <WorkspaceSwitcher name={ws.data?.name} accounts={accounts.data?.length} />
      {user && (
        <div className="flex items-center gap-2 px-1 text-sm">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-bold text-accent" aria-hidden>
            {(user.name || user.email).slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{user.name || user.email}</span>
            <span className="block text-xs text-muted">{ROLE_LABEL[user.role]}</span>
          </span>
          <button onClick={signOut} className="rounded p-1.5 text-muted hover:bg-paper hover:text-ink" aria-label="Sign out" title="Sign out">
            <LogOut size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

function WorkspaceSwitcher({ name, accounts }: { name?: string; accounts?: number }) {
  const { state } = useAuth();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const list = state?.workspaces ?? [];
  const canCreate = !!state?.user && (state.user.is_admin || list.some((w) => w.role === "owner"));
  const go = () => {
    window.location.href = "/"; // fresh start: every screen reloads for the new workspace
  };
  async function create() {
    try {
      await api.createWorkspace(newName.trim());
      go();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="w-full rounded-md border border-line p-3 text-left text-sm hover:border-accent"
      >
        <div className="flex items-center justify-between text-xs text-muted">
          Workspace {list.length > 1 && <span className="rounded bg-paper px-1 font-mono">{list.length}</span>}
        </div>
        <div className="truncate font-semibold">{name ?? state?.workspace?.name ?? "…"}</div>
        <div className="mt-1 text-xs text-muted">{accounts !== undefined ? `${accounts} account${accounts === 1 ? "" : "s"} · self-hosted` : "self-hosted"}</div>
      </button>
      {open && (
        <div role="menu" className="absolute bottom-full left-0 z-50 mb-2 flex w-full min-w-56 flex-col gap-0.5 rounded-md border border-line bg-surface p-1.5 text-sm shadow-lg">
          {list.map((w) => (
            <button
              key={w.id}
              role="menuitem"
              disabled={w.current}
              onClick={() => api.switchWorkspace(w.id).then(go).catch((e) => setError(e instanceof Error ? e.message : String(e)))}
              className={cx("flex items-center justify-between gap-2 rounded px-2.5 py-1.5 text-left", w.current ? "bg-accent-soft text-accent" : "hover:bg-paper")}
            >
              <span className="truncate">{w.name}</span>
              <span className="shrink-0 text-xs text-muted">{w.role}</span>
            </button>
          ))}
          {canCreate &&
            (creating ? (
              <form
                className="flex flex-col gap-1.5 border-t border-line p-1.5 pt-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  create();
                }}
              >
                <input autoFocus aria-label="New workspace name" placeholder="e.g. Leo Cooks" value={newName} onChange={(e) => setNewName(e.target.value)} className="rounded border border-line bg-paper px-2 py-1.5" />
                <button type="submit" disabled={!newName.trim()} className="rounded bg-accent px-2 py-1.5 font-medium text-surface disabled:opacity-50">Create and switch</button>
              </form>
            ) : (
              <button role="menuitem" onClick={() => setCreating(true)} className="rounded border-t border-line px-2.5 py-1.5 text-left text-accent hover:bg-paper">
                + New workspace
              </button>
            ))}
          {error && <p className="px-2.5 py-1 text-xs text-rec">{error}</p>}
        </div>
      )}
    </div>
  );
}

function RoleNotice() {
  const { state } = useAuth();
  const role = state?.user?.role;
  if (role !== "viewer" && role !== "reviewer") return null;
  return (
    <p className="-mb-2 rounded border border-line bg-paper px-3 py-2 text-xs text-muted">
      {role === "viewer" ? "You have view-only access. Ask an owner if you need to change things." : "Reviewer access: you can approve clips, batches and replies. Other changes need an editor or owner."}
    </p>
  );
}

function Toast() {
  const { toast } = useStore();
  if (!toast) return null;
  return (
    <div role="status" className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-md bg-ink px-4 py-2.5 text-sm font-medium text-paper shadow-lg">
      {toast}
    </div>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  if (BARE.some((p) => path.startsWith(p))) {
    return (
      <main className="flex min-h-screen flex-col items-center px-4 py-10">
        <div className="mb-8 flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-rec" aria-hidden />
          <span className="text-lg font-extrabold tracking-tight">clip_star</span>
        </div>
        {children}
        <Toast />
      </main>
    );
  }
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-surface lg:block">
        <div className="sticky top-0 flex h-screen flex-col gap-6 px-3 py-5">
          <div className="flex items-center justify-between">
            <Brand />
            <NotificationsBell />
          </div>
          <Nav />
          <div className="mt-auto">
            <Workspace />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface px-4 py-3 lg:hidden">
          <Brand />
          <div className="flex items-center gap-1">
            <NotificationsBell />
            <button className="rounded p-1.5 hover:bg-paper" onClick={() => setOpen(true)} aria-label="Open menu">
              <Menu size={20} />
            </button>
          </div>
        </div>
        {open && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-ink/40" onClick={() => setOpen(false)} />
            <div className="absolute inset-y-0 left-0 flex w-64 flex-col gap-6 bg-surface px-3 py-5">
              <div className="flex items-center justify-between">
                <Brand />
                <button className="rounded p-1.5 hover:bg-paper" onClick={() => setOpen(false)} aria-label="Close menu">
                  <X size={18} />
                </button>
              </div>
              <Nav onNavigate={() => setOpen(false)} />
              <div className="mt-auto">
                <Workspace />
              </div>
            </div>
          </div>
        )}
        <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <RoleNotice />
          {children}
        </main>
      </div>
      <Toast />
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <StoreProvider>
      <AuthProvider>
        <Frame>{children}</Frame>
      </AuthProvider>
    </StoreProvider>
  );
}
