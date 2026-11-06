"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import {
  Activity,
  BarChart3,
  Blocks,
  CalendarDays,
  Film,
  LayoutDashboard,
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
  const { comments } = useStore();
  // Clips is live: count real clips waiting for approval (no badge if the API is unreachable).
  const pending = usePoll(() => api.clips({ status: "pending" }), { intervalMs: 15000 });
  const awaiting = usePoll(api.batches, { intervalMs: 15000 });
  return {
    "/clips": pending.data?.length ?? 0,
    "/publishing": awaiting.data?.filter((b) => b.status === "awaiting").length ?? 0,
    "/engage": comments.filter((c) => c.status === "open" && c.category !== "spam").length,
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

function Workspace() {
  const ws = usePoll(api.workspace, { intervalMs: 60000 });
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  return (
    <div className="rounded-md border border-line p-3 text-sm">
      <div className="text-xs text-muted">Workspace</div>
      <div className="truncate font-semibold">{ws.data?.name ?? "…"}</div>
      <div className="mt-1 text-xs text-muted">{accounts.data ? `${accounts.data.length} account${accounts.data.length === 1 ? "" : "s"} · self-hosted` : "self-hosted"}</div>
    </div>
  );
}

// Screens connected to the real backend so far. Everything else still shows sample data.
const LIVE = ["/videos", "/activity", "/clips", "/settings", "/engines", "/accounts", "/publishing", "/calendar", "/posts"];

function SampleNotice() {
  const path = usePathname();
  if (LIVE.some((p) => path.startsWith(p))) return null;
  if (path.startsWith("/videos/") ) return null;
  return (
    <p className="-mb-2 rounded border border-paid/30 bg-paid-soft px-3 py-2 text-xs text-paid">
      Sample data. This screen connects to the backend in a later build phase. Overview, Engage and Analytics connect in the next phases.
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
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-surface lg:block">
        <div className="sticky top-0 flex h-screen flex-col gap-6 px-3 py-5">
          <Brand />
          <Nav />
          <div className="mt-auto">
            <Workspace />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface px-4 py-3 lg:hidden">
          <Brand />
          <button className="rounded p-1.5 hover:bg-paper" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu size={20} />
          </button>
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
          <SampleNotice />
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
      <Frame>{children}</Frame>
    </StoreProvider>
  );
}
