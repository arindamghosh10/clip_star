"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { api, fmtTime } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import { cx } from "./ui";

const tone = { info: "bg-accent", warn: "bg-gate", error: "bg-rec" } as const;

export function NotificationsBell() {
  const n = usePoll(api.notifications, { intervalMs: 30000 });
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const unread = n.data?.unread ?? 0;

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => api.notificationsSeen().then(() => n.refresh()).catch(() => undefined), 1500);
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      clearTimeout(t);
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <div className="relative" ref={box}>
      <button
        className="relative rounded p-1.5 text-muted hover:bg-paper hover:text-ink"
        onClick={() => setOpen((o) => !o)}
        aria-label={unread ? `Notifications, ${unread} new` : "Notifications"}
        aria-expanded={open}
      >
        <Bell size={18} />
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-rec px-1 font-mono text-[10px] leading-4 text-white">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-50 flex max-h-[70vh] w-[min(22rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-md border border-line bg-surface shadow-lg lg:left-0 lg:right-auto">
          <div className="border-b border-line px-4 py-2.5 text-sm font-semibold">Notifications</div>
          <ul className="flex-1 overflow-y-auto">
            {!n.data?.items.length && <li className="px-4 py-6 text-center text-sm text-muted">Nothing yet.</li>}
            {n.data?.items.map((it) => {
              const inner = (
                <span className="flex gap-2.5">
                  <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", it.unread ? tone[it.severity] : "bg-line")} aria-hidden />
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className={cx("text-sm", it.unread && "font-semibold")}>{it.title}</span>
                    {it.body && <span className="line-clamp-2 text-xs text-muted">{it.body}</span>}
                    <span className="font-mono text-[11px] text-muted">{fmtTime(it.created_at)}</span>
                  </span>
                </span>
              );
              return (
                <li key={it.id} className="border-b border-line last:border-0">
                  {it.link ? (
                    <Link href={it.link} onClick={() => setOpen(false)} className="block px-4 py-3 hover:bg-paper">
                      {inner}
                    </Link>
                  ) : (
                    <div className="px-4 py-3">{inner}</div>
                  )}
                </li>
              );
            })}
          </ul>
          <Link href="/settings#notifications" onClick={() => setOpen(false)} className="border-t border-line px-4 py-2 text-xs font-medium text-accent">
            Email settings
          </Link>
        </div>
      )}
    </div>
  );
}
