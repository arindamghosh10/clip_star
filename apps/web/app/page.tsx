"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowRight, Upload } from "lucide-react";
import { PipelineRail } from "@/components/PipelineRail";
import { Badge, Button, Card, PageHeader, PlatformBadge, Progress, Stat } from "@/components/ui";
import { CALENDAR, DAYS, INSIGHTS, PERFORMANCE, STAGES, VIDEOS } from "@/lib/data";
import { useStore } from "@/lib/store";

export default function Overview() {
  const { clips, batches, comments, accounts } = useStore();
  const processing = VIDEOS.filter((v) => v.status === "processing");
  const pendingClips = clips.filter((c) => c.status === "pending");
  const awaiting = batches.filter((b) => b.status === "awaiting");
  const openReplies = comments.filter((c) => c.status === "open" && c.category !== "spam");
  const reconnect = accounts.filter((a) => a.status === "reconnect");
  const scheduled = CALENDAR.filter((e) => batches.find((b) => b.id === e.batch)?.status !== "disabled");

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Good morning, Maya"
        description="Here's what the pipeline is doing and what needs you."
        actions={
          <Link href="/videos">
            <Button variant="primary">
              <Upload size={16} /> Add video
            </Button>
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Views · last 7 days" value="148.5k" delta="+38% vs previous week" />
        <Stat label="Follows gained" value="+976" delta="+22%" />
        <Stat label="Posts scheduled" value={String(scheduled.reduce((n, e) => n + e.count, 0))} />
        <Stat label="Connected accounts" value={String(accounts.length)} />
      </div>

      <Card title="Pipeline" actions={<span className="text-xs text-muted">Ep. 113 is at stage 03</span>}>
        <PipelineRail current={processing[0]?.stage} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-4">
        <Column title="Processing" count={processing.length}>
          {processing.map((v) => (
            <Link key={v.id} href={`/videos/${v.id}`} className="flex flex-col gap-1.5 rounded border border-line bg-paper p-3 text-sm hover:border-accent">
              <span className="font-semibold">{v.title}</span>
              <span className="font-mono text-xs text-muted">
                Stage {String(STAGES.findIndex((s) => s.id === v.stage) + 1).padStart(2, "0")} · {STAGES.find((s) => s.id === v.stage)?.name}
              </span>
              <Progress value={v.progress} />
            </Link>
          ))}
        </Column>

        <Column title="Needs you" count={(pendingClips.length ? 1 : 0) + awaiting.length + (openReplies.length ? 1 : 0) + reconnect.length}>
          {pendingClips.length > 0 && (
            <TaskCard href="/clips" title={`${pendingClips.length} clips to approve`} meta={`Ep. 112 · scores ${pendingClips.map((c) => c.score).join(", ")}`} />
          )}
          {awaiting.map((b) => (
            <TaskCard key={b.id} href="/publishing" title={`Approve batch ${b.id}`} meta={`${b.posts} posts · ${b.accounts} accounts`} />
          ))}
          {openReplies.length > 0 && <TaskCard href="/engage" title={`${openReplies.length} reply drafts`} meta="Questions, praise, leads" />}
          {reconnect.map((a) => (
            <TaskCard key={a.id} href="/accounts" title={`Reconnect ${a.handle}`} meta="Login expires in 3 days" />
          ))}
        </Column>

        <Column title="Scheduled" count={scheduled.length}>
          {scheduled.slice(0, 4).map((e, i) => (
            <div key={i} className="flex flex-col gap-1 rounded border border-line bg-paper p-3 text-sm">
              <span className="font-semibold">{e.clip}</span>
              <span className="flex items-center gap-1.5 font-mono text-xs text-muted">
                {DAYS[e.day]} {e.time} · <PlatformBadge platform={e.platform} /> ×{e.count}
              </span>
            </div>
          ))}
          <Link href="/calendar" className="text-xs font-medium text-accent">
            Open calendar →
          </Link>
        </Column>

        <Column title="Live" count={PERFORMANCE.length}>
          {PERFORMANCE.slice(0, 4).map((p) => (
            <div key={p.clip} className="flex flex-col gap-1 rounded border border-line bg-paper p-3 text-sm">
              <span className="font-semibold">{p.clip}</span>
              <span className="tnum flex items-center gap-1.5 font-mono text-xs text-muted">
                <PlatformBadge platform={p.platform} /> {(p.views / 1000).toFixed(1)}k views · {p.watched}% watched
              </span>
            </div>
          ))}
        </Column>
      </div>

      <Card title="Insights this week" actions={<Link href="/analytics" className="text-sm font-medium text-accent">All insights</Link>}>
        <div className="grid gap-3 md:grid-cols-3">
          {INSIGHTS.slice(0, 3).map((i) => (
            <div key={i.title} className="flex flex-col gap-1 rounded bg-accent-soft p-3 text-sm">
              <Badge tone={i.kind === "do" ? "free" : i.kind === "avoid" ? "rec" : "accent"} className="self-start">
                {i.kind === "do" ? "Do more" : i.kind === "avoid" ? "Do less" : "Idea"}
              </Badge>
              <span className="font-semibold">{i.title}</span>
              <span className="text-muted">{i.body}</span>
            </div>
          ))}
        </div>
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
      <span className="flex flex-col gap-0.5">
        <span className="font-semibold">{title}</span>
        <span className="font-mono text-xs text-muted">{meta}</span>
      </span>
      <ArrowRight size={14} className="mt-1 text-gate" />
    </Link>
  );
}
