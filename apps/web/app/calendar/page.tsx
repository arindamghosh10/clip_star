"use client";

import { useMemo, useState, type DragEvent } from "react";
import { ChevronLeft, ChevronRight, GripVertical } from "lucide-react";
import { useAuth } from "@/components/Auth";
import { Button, Card, PageHeader, PlatformBadge, cx } from "@/components/ui";
import { ApiError, api, type ApiPost } from "@/lib/api";
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

const movable = (p: ApiPost) => p.status === "held" || p.status === "scheduled";

/** "2026-11-07T09:30" in the browser's local time, for <input type="datetime-local">. */
function localInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

type Ask = { post: ApiPost; at: Date; warnings: string[] };

export default function Calendar() {
  const { notify } = useStore();
  const { can } = useAuth();
  const canMove = can("editor");
  const [week, setWeek] = useState(() => startOfWeek(new Date()));
  const [open, setOpen] = useState<string | null>(null);
  const [when, setWhen] = useState("");
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const [ask, setAsk] = useState<Ask | null>(null);
  const posts = usePoll(() => api.posts({ limit: 1000 }), {
    intervalMs: 10000,
  });
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  const clips = usePoll(() => api.clips(), { intervalMs: 60000 });
  const acc = useMemo(
    () => new Map((accounts.data ?? []).map((a) => [a.id, a])),
    [accounts.data],
  );
  const cl = useMemo(
    () => new Map((clips.data ?? []).map((c) => [c.id, c])),
    [clips.data],
  );
  const byId = useMemo(
    () => new Map((posts.data ?? []).map((p) => [p.id, p])),
    [posts.data],
  );
  const days = Array.from(
    { length: 7 },
    (_, i) => new Date(week.getTime() + i * DAY),
  );

  const byDay = useMemo(() => {
    const m = new Map<number, ApiPost[]>();
    for (const p of posts.data ?? []) {
      const t = new Date(p.published_at ?? p.scheduled_at);
      const d = new Date(t);
      d.setHours(0, 0, 0, 0);
      if (d < week || d.getTime() >= week.getTime() + 7 * DAY) continue;
      m.set(
        d.getTime(),
        [...(m.get(d.getTime()) ?? []), p].sort(
          (a, b) =>
            +new Date(a.published_at ?? a.scheduled_at) -
            +new Date(b.published_at ?? b.scheduled_at),
        ),
      );
    }
    return m;
  }, [posts.data, week]);

  async function move(p: ApiPost, at: Date, force = false) {
    if (at.getTime() < Date.now() + 2 * 60000) {
      notify("Pick a time at least 2 minutes from now.");
      return;
    }
    try {
      const r = await api.reschedulePost(p.id, at.toISOString(), force);
      notify(
        `Moved to ${at.toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })}${r.warnings.length ? " (rule warnings noted on the post)" : ""}`,
      );
      setAsk(null);
      setOpen(null);
      posts.refresh();
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status === 409 &&
        Array.isArray(e.data?.warnings)
      )
        setAsk({ post: p, at, warnings: e.data.warnings as string[] });
      else notify(e instanceof Error ? e.message : String(e));
    }
  }

  function dropOn(day: Date, e: DragEvent) {
    e.preventDefault();
    setOver(null);
    const p = byId.get(e.dataTransfer.getData("text/plain"));
    setDragging(null);
    if (!p) return;
    const old = new Date(p.scheduled_at);
    const at = new Date(day);
    at.setHours(old.getHours(), old.getMinutes(), 0, 0); // same time of day, new date
    if (at.getTime() === old.getTime()) return;
    move(p, at);
  }

  async function cancel(p: ApiPost) {
    try {
      await api.postAction(p.id, "cancel");
      notify("Post switched off");
      setOpen(null);
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
        description={
          canMove
            ? "Every post across all accounts, in your local time. Drag a waiting post to another day, or click it to pick an exact time or switch it off."
            : "Every post across all accounts, in your local time."
        }
        actions={
          <span className="flex items-center gap-2">
            <Button
              size="sm"
              aria-label="Previous week"
              onClick={() => setWeek(new Date(week.getTime() - 7 * DAY))}
            >
              <ChevronLeft size={14} />
            </Button>
            <span className="text-sm font-medium">
              {days[0].toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              })}{" "}
              –{" "}
              {days[6].toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              })}
            </span>
            <Button
              size="sm"
              aria-label="Next week"
              onClick={() => setWeek(new Date(week.getTime() + 7 * DAY))}
            >
              <ChevronRight size={14} />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setWeek(startOfWeek(new Date()))}
            >
              Today
            </Button>
          </span>
        }
      />
      {posts.error && <p className="text-sm text-rec">{posts.error}</p>}
      {ask && (
        <div
          role="alertdialog"
          aria-label="Move anyway?"
          className="flex flex-col gap-2 rounded-md border border-gate/40 bg-gate-soft p-4 text-sm"
        >
          <span className="font-semibold">
            Moving to{" "}
            {ask.at.toLocaleString(undefined, {
              weekday: "short",
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}{" "}
            breaks a posting rule:
          </span>
          <ul className="list-disc pl-5">
            {ask.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          <span className="flex gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => move(ask.post, ask.at, true)}
            >
              Move anyway
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setAsk(null)}>
              Keep it where it was
            </Button>
          </span>
        </div>
      )}
      <Card padded={false}>
        <div className="overflow-x-auto">
          <div className="grid min-w-[840px] grid-cols-7 gap-px bg-line">
            {days.map((d) => {
              const past = d.getTime() + DAY < Date.now();
              return (
                <div
                  key={d.getTime()}
                  onDragOver={(e) => {
                    if (!dragging || past) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = "move";
                    setOver(d.getTime());
                  }}
                  onDragLeave={() =>
                    setOver((o) => (o === d.getTime() ? null : o))
                  }
                  onDrop={(e) => dropOn(d, e)}
                  className={cx(
                    "flex min-h-[320px] flex-col gap-1.5 bg-surface p-2 transition-colors",
                    over === d.getTime() &&
                      "bg-accent-soft/60 outline outline-2 -outline-offset-2 outline-accent",
                    dragging && past && "opacity-60",
                  )}
                  aria-label={d.toLocaleDateString(undefined, {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                  })}
                >
                  <h3 className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted">
                    {d.toLocaleDateString(undefined, {
                      weekday: "short",
                      day: "numeric",
                    })}
                  </h3>
                  {(byDay.get(d.getTime()) ?? []).map((p) => {
                    const a = acc.get(p.account_id);
                    const m = canMove && movable(p);
                    const clickable = can("reviewer") && movable(p); // reviewers may switch posts off, not move them
                    return (
                      <div
                        key={p.id}
                        draggable={m}
                        onDragStart={(e) => {
                          e.dataTransfer.setData("text/plain", p.id);
                          e.dataTransfer.effectAllowed = "move";
                          setDragging(p.id);
                          setOpen(null);
                        }}
                        onDragEnd={() => {
                          setDragging(null);
                          setOver(null);
                        }}
                        className={cx(
                          "flex flex-col gap-0.5 rounded px-2 py-1.5 text-xs",
                          tone[p.status],
                          m && "cursor-grab active:cursor-grabbing",
                          dragging === p.id && "opacity-40",
                        )}
                      >
                        <button
                          className="flex flex-col gap-0.5 text-left disabled:cursor-default"
                          disabled={!clickable}
                          onClick={() => {
                            setOpen(open === p.id ? null : p.id);
                            setWhen(localInput(new Date(p.scheduled_at)));
                          }}
                          title={
                            m
                              ? "Drag to another day, or click for options"
                              : clickable
                                ? "Click to switch off"
                                : p.status
                          }
                        >
                          <span className="flex items-center gap-1 font-mono text-[11px]">
                            {m && (
                              <GripVertical
                                size={11}
                                className="-ml-1 text-muted"
                                aria-hidden
                              />
                            )}
                            {new Date(
                              p.published_at ?? p.scheduled_at,
                            ).toLocaleTimeString(undefined, {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                            {a && <PlatformBadge platform={a.platform} />}
                          </span>
                          <span className="font-medium">
                            {cl.get(p.clip_id)?.title ?? "Clip"}
                          </span>
                          <span className="truncate text-[10px] text-muted">
                            {a?.handle}
                          </span>
                          {p.last_error?.startsWith("Moved by hand") && (
                            <span
                              className="text-[10px] text-paid"
                              title={p.last_error}
                            >
                              moved outside the rules
                            </span>
                          )}
                        </button>
                        {open === p.id && (
                          <span className="flex flex-col gap-1.5 pt-1">
                            {m && (
                              <label className="flex flex-col gap-0.5 text-[11px] text-muted">
                                Move to
                                <input
                                  type="datetime-local"
                                  value={when}
                                  min={localInput(
                                    new Date(Date.now() + 5 * 60000),
                                  )}
                                  onChange={(e) => setWhen(e.target.value)}
                                  className="rounded border border-line bg-surface px-1.5 py-1 text-xs text-ink"
                                />
                              </label>
                            )}
                            <span className="flex flex-wrap gap-1">
                              {m && (
                                <Button
                                  size="sm"
                                  variant="primary"
                                  disabled={!when}
                                  onClick={() => move(p, new Date(when))}
                                >
                                  Move
                                </Button>
                              )}
                              <Button
                                size="sm"
                                variant="danger"
                                onClick={() => cancel(p)}
                              >
                                Switch off
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setOpen(null)}
                              >
                                Close
                              </Button>
                            </span>
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </Card>
      <p className="text-sm text-muted">
        Green = posted · blue = scheduled · grey = waiting for batch approval ·
        amber = checking with the platform · red = failed. Moves keep each
        account&apos;s posting rules; you&apos;re asked before breaking one.
      </p>
    </>
  );
}
