"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button, Card, PageHeader, PlatformBadge, cx } from "@/components/ui";
import { api, type ApiPost } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const DAY = 86400000;

function startOfWeek(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); // Monday
  return x;
}

const tone: Record<ApiPost["status"], string> = {
  held: "bg-paper text-muted",
  scheduled: "bg-accent-soft",
  publishing: "bg-gate-soft",
  published: "bg-free-soft",
  failed: "bg-rec/10 text-rec",
  unknown: "bg-paid-soft",
  cancelled: "bg-paper text-muted line-through",
};

export default function Calendar() {
  const { notify } = useStore();
  const [week, setWeek] = useState(() => startOfWeek(new Date()));
  const [pending, setPending] = useState<string | null>(null);
  const posts = usePoll(() => api.posts({ limit: 1000 }), { intervalMs: 10000 });
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  const clips = usePoll(() => api.clips(), { intervalMs: 60000 });
  const acc = useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a])), [accounts.data]);
  const cl = useMemo(() => new Map((clips.data ?? []).map((c) => [c.id, c])), [clips.data]);
  const days = Array.from({ length: 7 }, (_, i) => new Date(week.getTime() + i * DAY));

  const byDay = useMemo(() => {
    const m = new Map<number, ApiPost[]>();
    for (const p of posts.data ?? []) {
      const t = new Date(p.published_at ?? p.scheduled_at);
      const d = new Date(t);
      d.setHours(0, 0, 0, 0);
      if (d < week || d.getTime() >= week.getTime() + 7 * DAY) continue;
      m.set(d.getTime(), [...(m.get(d.getTime()) ?? []), p].sort((a, b) => +new Date(a.published_at ?? a.scheduled_at) - +new Date(b.published_at ?? b.scheduled_at)));
    }
    return m;
  }, [posts.data, week]);

  async function cancel(p: ApiPost) {
    try {
      await api.postAction(p.id, "cancel");
      notify("Post switched off");
      setPending(null);
      posts.refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Stage 06 · Publish"
        title="Calendar"
        description="Every post across all accounts, in your local time. Click a waiting post to switch it off."
        actions={
          <span className="flex items-center gap-2">
            <Button size="sm" aria-label="Previous week" onClick={() => setWeek(new Date(week.getTime() - 7 * DAY))}>
              <ChevronLeft size={14} />
            </Button>
            <span className="text-sm font-medium">
              {days[0].toLocaleDateString(undefined, { month: "short", day: "numeric" })} – {days[6].toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </span>
            <Button size="sm" aria-label="Next week" onClick={() => setWeek(new Date(week.getTime() + 7 * DAY))}>
              <ChevronRight size={14} />
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setWeek(startOfWeek(new Date()))}>
              Today
            </Button>
          </span>
        }
      />
      {posts.error && <p className="text-sm text-rec">{posts.error}</p>}
      <Card padded={false}>
        <div className="overflow-x-auto">
          <div className="grid min-w-[840px] grid-cols-7 gap-px bg-line">
            {days.map((d) => (
              <div key={d.getTime()} className="flex min-h-[320px] flex-col gap-1.5 bg-surface p-2">
                <h3 className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted">{d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" })}</h3>
                {(byDay.get(d.getTime()) ?? []).map((p) => {
                  const a = acc.get(p.account_id);
                  const can = p.status === "held" || p.status === "scheduled";
                  return (
                    <div key={p.id} className={cx("flex flex-col gap-0.5 rounded px-2 py-1.5 text-xs", tone[p.status])}>
                      <button className="flex flex-col gap-0.5 text-left disabled:cursor-default" disabled={!can} onClick={() => setPending(pending === p.id ? null : p.id)} title={can ? "Switch this post off" : p.status}>
                        <span className="flex items-center gap-1 font-mono text-[11px]">
                          {new Date(p.published_at ?? p.scheduled_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                          {a && <PlatformBadge platform={a.platform} />}
                        </span>
                        <span className="font-medium">{cl.get(p.clip_id)?.title ?? "Clip"}</span>
                        <span className="truncate text-[10px] text-muted">{a?.handle}</span>
                      </button>
                      {pending === p.id && (
                        <span className="flex gap-1 pt-1">
                          <Button size="sm" variant="danger" onClick={() => cancel(p)}>
                            Switch off
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
                            Keep
                          </Button>
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </Card>
      <p className="text-sm text-muted">Green = posted · blue = scheduled · grey = waiting for batch approval · amber = checking with the platform · red = failed.</p>
    </>
  );
}
