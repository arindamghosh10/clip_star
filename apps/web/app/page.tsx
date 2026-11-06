"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, Upload } from "lucide-react";
import { InsightCard, PracticeNote } from "@/components/Analytics";
import { PipelineRail } from "@/components/PipelineRail";
import { Card, EmptyNote, PageHeader, PlatformBadge, Progress, Stat } from "@/components/ui";
import { api, fmtDelta, fmtNum, fmtTime } from "@/lib/api";
import { STAGES } from "@/lib/data";
import { usePoll } from "@/lib/usePoll";
import { Button } from "@/components/ui";

export default function Overview() {
  const ws = usePoll(api.workspace, { intervalMs: 60000 });
  const videos = usePoll(api.videos, { intervalMs: 5000 });
  const pending = usePoll(() => api.clips({ status: "pending" }), { intervalMs: 15000 });
  const batches = usePoll(api.batches, { intervalMs: 15000 });
  const comments = usePoll(api.commentSummary, { intervalMs: 30000 });
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  const scheduled = usePoll(() => api.posts({ status: "scheduled", limit: 200 }), { intervalMs: 30000 });
  const ov = usePoll(() => api.analytics(7), { intervalMs: 60000 });
  const learn = usePoll(api.learn, { intervalMs: 300000 });

  const processing = (videos.data ?? []).filter((v) => v.status === "queued" || v.status === "processing");
  const awaiting = (batches.data ?? []).filter((b) => b.status === "awaiting");
  const openReplies = Object.entries(comments.data?.open ?? {}).reduce((n, [k, v]) => (k === "spam" ? n : n + (v ?? 0)), 0);
  const reconnect = (accounts.data ?? []).filter((a) => a.status === "reconnect");
  const accById = new Map((accounts.data ?? []).map((a) => [a.id, a]));
  const upcoming = [...(scheduled.data ?? [])].sort((a, b) => a.scheduled_at.localeCompare(b.scheduled_at));
  const t = ov.data?.totals;
  const p = ov.data?.previous;
  const needs = (pending.data?.length ? 1 : 0) + awaiting.length + (openReplies ? 1 : 0) + reconnect.length;

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title={ws.data?.name ?? "Overview"}
        description="What the pipeline is doing, what needs you, and how posts are doing."
        actions={
          <Link href="/videos">
            <Button variant="primary">
              <Upload size={16} /> Add video
            </Button>
          </Link>
        }
      />
      {ov.error && <p role="alert" className="rounded bg-rec/10 p-3 text-sm text-rec">{ov.error}</p>}
      <PracticeNote show={!!t && t.practice_posts > 0} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Views · last 7 days" value={t ? fmtNum(t.views) : "…"} delta={t && p ? fmtDelta(t.views, p.views) : undefined} />
        <Stat label="Follows gained · 7 days" value={t ? (t.follower_gain != null ? `${t.follower_gain >= 0 ? "+" : ""}${fmtNum(t.follower_gain)}` : t.follows ? `+${fmtNum(t.follows)}` : "—") : "…"} />
        <Stat label="Posts scheduled" value={String(ov.data?.scheduled ?? "…")} />
        <Stat label="Accounts" value={accounts.data ? String(accounts.data.length) : "…"} delta={reconnect.length ? `${reconnect.length} need reconnecting` : undefined} />
      </div>

      <Card title="Pipeline" actions={processing[0] ? <span className="text-xs text-muted">{processing[0].title} · {STAGES.find((s) => s.id === processing[0].stage)?.name}</span> : <span className="text-xs text-muted">Idle</span>}>
        <PipelineRail current={processing[0]?.stage} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-4">
        <Column title="Processing" count={processing.length}>
          {processing.length === 0 && <EmptyNote>Nothing processing.</EmptyNote>}
          {processing.slice(0, 4).map((v) => (
            <Link key={v.id} href={`/videos/${v.id}`} className="flex flex-col gap-1.5 rounded border border-line bg-paper p-3 text-sm hover:border-accent">
              <span className="truncate font-semibold">{v.title}</span>
              <span className="font-mono text-xs text-muted">
                Stage {String(STAGES.findIndex((s) => s.id === v.stage) + 1).padStart(2, "0")} · {STAGES.find((s) => s.id === v.stage)?.name}
              </span>
              <Progress value={v.progress} />
            </Link>
          ))}
        </Column>

        <Column title="Needs you" count={needs}>
          {needs === 0 && <EmptyNote>All clear.</EmptyNote>}
          {!!pending.data?.length && <TaskCard href="/clips" title={`${pending.data.length} clip${pending.data.length === 1 ? "" : "s"} to approve`} meta={`Top score ${Math.max(...pending.data.map((c) => c.score))}`} />}
          {awaiting.map((b) => (
            <TaskCard key={b.id} href="/publishing" title={`Approve “${b.name}”`} meta={`${b.posts} posts · ${b.accounts} accounts`} />
          ))}
          {openReplies > 0 && <TaskCard href="/engage" title={`${openReplies} comment${openReplies === 1 ? "" : "s"} to answer`} meta="Questions, praise, leads" />}
          {reconnect.map((a) => (
            <TaskCard key={a.id} href={`/accounts/${a.id}`} title={`Reconnect ${a.handle}`} meta={a.last_error ?? "Login expired"} />
          ))}
        </Column>

        <Column title="Scheduled" count={upcoming.length}>
          {upcoming.length === 0 && <EmptyNote>Nothing scheduled.</EmptyNote>}
          {upcoming.slice(0, 4).map((post) => {
            const a = accById.get(post.account_id);
            return (
              <div key={post.id} className="flex flex-col gap-1 rounded border border-line bg-paper p-3 text-sm">
                <span className="line-clamp-2 font-semibold">{post.caption.split("\n")[0] || "Post"}</span>
                <span className="flex items-center gap-1.5 font-mono text-xs text-muted">
                  {a && <PlatformBadge platform={a.platform} />} {a?.handle} · {fmtTime(post.scheduled_at)}
                </span>
              </div>
            );
          })}
          <Link href="/calendar" className="text-xs font-medium text-accent">
            Open calendar →
          </Link>
        </Column>

        <Column title="Best this week" count={ov.data?.top_posts.length ?? 0}>
          {ov.data && ov.data.top_posts.length === 0 && <EmptyNote>No stats yet.</EmptyNote>}
          {ov.data?.top_posts.slice(0, 4).map((tp) => (
            <Link key={tp.post_id} href={`/clips/${tp.clip_id}`} className="flex flex-col gap-1 rounded border border-line bg-paper p-3 text-sm hover:border-accent">
              <span className="truncate font-semibold">{tp.clip_title}</span>
              <span className="tnum flex items-center gap-1.5 font-mono text-xs text-muted">
                <PlatformBadge platform={tp.platform} /> {fmtNum(tp.views)} views{tp.watch_pct != null ? ` · ${Math.round(tp.watch_pct)}% watched` : ""}
              </span>
            </Link>
          ))}
        </Column>
      </div>

      <Card title="What works for you" actions={<Link href="/analytics" className="text-sm font-medium text-accent">Analytics</Link>}>
        {learn.data && learn.data.insights.length === 0 ? (
          <EmptyNote>No clear patterns yet. They appear once enough posts have stats ({learn.data.n} so far).</EmptyNote>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {learn.data?.insights.slice(0, 3).map((i) => <InsightCard key={i.dimension + i.title} i={i} compact />)}
          </div>
        )}
      </Card>
    </>
  );
}

function Column({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
      <h3 className="flex justify-between font-mono text-xs uppercase tracking-wider text-muted">
        {title} <span>{count}</span>
      </h3>
      {children}
    </div>
  );
}

function TaskCard({ href, title, meta }: { href: string; title: string; meta: string }) {
  return (
    <Link href={href} className="group flex items-start justify-between gap-2 rounded border border-gate/30 bg-gate-soft p-3 text-sm hover:border-gate">
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="font-semibold">{title}</span>
        <span className="truncate font-mono text-xs text-muted">{meta}</span>
      </span>
      <ArrowRight size={14} className="mt-1 shrink-0 text-gate" />
    </Link>
  );
}
