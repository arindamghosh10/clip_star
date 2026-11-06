"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { InsightCard, PracticeNote, TopPostsTable, ViewsChart } from "@/components/Analytics";
import { Badge, Button, Card, EmptyNote, PageHeader, PlatformBadge, Stat, cx } from "@/components/ui";
import { api, fmtDelta, fmtNum, fmtTime, type ApiReport } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const RANGES = [7, 30, 90] as const;

export default function Analytics() {
  const { notify } = useStore();
  const [days, setDays] = useState<number>(7);
  const ov = usePoll(() => api.analytics(days), { intervalMs: 60000, deps: [days] });
  const learn = usePoll(api.learn, { intervalMs: 120000 });
  const reports = usePoll(api.reports, { intervalMs: 120000 });
  const [open, setOpen] = useState<ApiReport | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function run(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key);
    try {
      await fn();
      notify(ok);
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const first = reports.data?.[0];
    if (first && !open) api.report(first.id).then(setOpen).catch(() => undefined);
  }, [reports.data, open]);

  const t = ov.data?.totals;
  const p = ov.data?.previous;
  const model = learn.data?.model;

  return (
    <>
      <PageHeader
        eyebrow="Measure & learn"
        title="Analytics"
        description="Stats are collected 1 hour, 1 day, 3 days and 7 days after each post and linked back to the clip, hook, length and version that made it."
        actions={
          <div className="flex gap-1 rounded border border-line bg-surface p-0.5" role="radiogroup" aria-label="Time range">
            {RANGES.map((d) => (
              <button key={d} role="radio" aria-checked={days === d} onClick={() => setDays(d)} className={cx("rounded px-3 py-1.5 text-sm font-medium", days === d ? "bg-ink text-paper" : "text-muted hover:text-ink")}>
                {d} days
              </button>
            ))}
          </div>
        }
      />
      {ov.error && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {ov.error}
        </p>
      )}
      <PracticeNote show={!!ov.data && ov.data.totals.practice_posts > 0} />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={`Views · ${days} days`} value={t ? fmtNum(t.views) : "…"} delta={t && p ? fmtDelta(t.views, p.views) : undefined} />
        <Stat label="Average watched" value={t?.watch_pct != null ? `${Math.round(t.watch_pct)}%` : "—"} delta={t?.watch_pct != null && p?.watch_pct != null ? `${t.watch_pct - p.watch_pct >= 0 ? "+" : ""}${(t.watch_pct - p.watch_pct).toFixed(0)} pts` : undefined} />
        <Stat label="Shares" value={t ? fmtNum(t.shares) : "…"} delta={t && p ? fmtDelta(t.shares, p.shares) : undefined} />
        <Stat
          label="Follows gained"
          value={t ? (t.follower_gain != null ? `${t.follower_gain >= 0 ? "+" : ""}${fmtNum(t.follower_gain)}` : t.follows ? `+${fmtNum(t.follows)}` : "—") : "…"}
          delta={t ? `${t.posts} posts · ${t.measured} with stats` : undefined}
        />
      </div>

      <Card title="Views by day posted · all accounts">
        {ov.data ? <ViewsChart series={ov.data.series} /> : <p className="text-sm text-muted">Loading…</p>}
        <p className="mt-2 text-xs text-muted">Each post&apos;s latest numbers, counted on the day it went out.</p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="By platform" padded={false}>
          <Breakdown rows={(ov.data?.by_platform ?? []).map((r) => ({ key: r.platform, label: <PlatformBadge platform={r.platform} full />, posts: r.posts, views: r.views }))} />
        </Card>
        <Card title="By account" padded={false}>
          <Breakdown
            rows={(ov.data?.by_account ?? []).slice(0, 8).map((r) => ({
              key: r.account_id,
              label: (
                <Link href={`/accounts/${r.account_id}`} className="flex items-center gap-1.5 hover:text-accent">
                  <PlatformBadge platform={r.platform} /> <span className="truncate">{r.handle}</span>
                </Link>
              ),
              posts: r.posts,
              views: r.views,
            }))}
          />
        </Card>
      </div>

      <Card title="Top posts" padded={false}>
        <TopPostsTable posts={ov.data?.top_posts ?? []} />
      </Card>

      <Card
        title="What works for you"
        actions={<span className="text-xs text-muted">{learn.data ? `Based on ${learn.data.n} posts with stats, last 90 days` : ""}</span>}
      >
        {learn.data && learn.data.insights.length === 0 && (
          <EmptyNote>
            No clear patterns yet. Insights appear once at least {learn.data.min_n} posts on each side of a comparison have stats and the difference is 20% or more, so they aren&apos;t just luck.
          </EmptyNote>
        )}
        <div className="grid gap-3 md:grid-cols-2">
          {learn.data?.insights.map((i) => <InsightCard key={i.dimension + i.title} i={i} />)}
        </div>
        {!!learn.data?.ideas.length && (
          <div className="mt-5 flex flex-col gap-2">
            <h3 className="font-mono text-xs uppercase tracking-wider text-muted">Ideas from viewer questions</h3>
            {learn.data.ideas.map((i) => (
              <div key={i.topic} className="rounded border border-line p-3 text-sm">
                <Badge tone="accent">Idea</Badge> <span className="font-semibold">{i.topic}</span> <span className="text-muted">· {i.body}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Learned scoring"
          actions={
            <Button size="sm" disabled={busy === "train"} onClick={() => run("train", () => api.train().then(() => learn.refresh()), "Scoring model retrained")}>
              <RefreshCw size={14} /> Retrain now
            </Button>
          }
        >
          <div className="flex flex-col gap-2 text-sm">
            <span className="flex items-center gap-2">
              <Badge tone={model?.active ? "free" : "neutral"}>{model?.active ? "On" : "Off"}</Badge>
              <span className="text-muted">{model ? `Trained ${fmtTime(model.trained_at)} on ${model.n} posts from ${model.clips} clips` : "Not trained yet"}</span>
            </span>
            <p>{model?.reason ?? "After enough posts have stats, clip_star learns which kinds of moments do best for you and uses that when picking new clips. It only switches on if it predicts better than the built-in rules."}</p>
            {model?.corr !== undefined && (
              <p className="font-mono text-xs text-muted">
                Ranking accuracy on held-out posts: model {model.corr?.toFixed(2)} · built-in rules {model.baseline_corr?.toFixed(2)}
              </p>
            )}
          </div>
        </Card>

        <Card title="Re-clip older videos">
          {!learn.data?.reclip.length ? (
            <EmptyNote>Nothing to suggest. Videos older than two weeks that haven&apos;t been posted from recently show up here.</EmptyNote>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {learn.data.reclip.map((r) => (
                <li key={r.video_id} className="flex items-center justify-between gap-3 rounded border border-line p-3">
                  <span className="min-w-0">
                    <Link href={`/videos/${r.video_id}`} className="font-semibold hover:text-accent">{r.title}</Link>
                    <span className="block text-xs text-muted">{r.reason}</span>
                  </span>
                  <Button size="sm" variant="primary" disabled={busy === r.video_id} onClick={() => run(r.video_id, () => api.reclip(r.video_id).then(() => learn.refresh()), "Finding new moments. Clips you approved or posted stay.")}>
                    Re-clip
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card
        title="Weekly reports"
        actions={
          <Button size="sm" disabled={busy === "report"} onClick={() => run("report", () => api.makeReport().then((r) => { setOpen(r); reports.refresh(); }), "Report created")}>
            Create report now
          </Button>
        }
      >
        {!reports.data?.length ? (
          <EmptyNote>A report is made automatically every week once something has been posted.</EmptyNote>
        ) : (
          <div className="grid gap-4 md:grid-cols-[220px_1fr]">
            <ul className="flex flex-col gap-1 text-sm">
              {reports.data.map((r) => (
                <li key={r.id}>
                  <button onClick={() => api.report(r.id).then(setOpen)} className={cx("w-full rounded px-2.5 py-1.5 text-left", open?.id === r.id ? "bg-accent-soft text-accent" : "hover:bg-paper")}>
                    Week to {fmtTime(r.period_end)}
                  </button>
                </li>
              ))}
            </ul>
            {open && (
              <div className="flex flex-col gap-3 text-sm">
                <p className="text-base">{open.summary}</p>
                {open.data.insights.slice(0, 4).map((i) => <InsightCard key={i.dimension + i.title} i={i} compact />)}
                <span className="text-xs text-muted">Created {fmtTime(open.created_at)}</span>
              </div>
            )}
          </div>
        )}
      </Card>
    </>
  );
}

function Breakdown({ rows }: { rows: { key: string; label: React.ReactNode; posts: number; views: number }[] }) {
  if (!rows.length) return <div className="p-5"><EmptyNote>No posts in this period.</EmptyNote></div>;
  const max = Math.max(1, ...rows.map((r) => r.views));
  return (
    <ul className="flex flex-col">
      {rows.map((r) => (
        <li key={r.key} className="flex items-center gap-3 border-b border-line px-5 py-2.5 text-sm last:border-0">
          <span className="w-44 min-w-0 shrink-0 truncate">{r.label}</span>
          <span className="h-2 flex-1 overflow-hidden rounded-full bg-line" aria-hidden>
            <span className="block h-full rounded-full bg-accent" style={{ width: `${(r.views / max) * 100}%` }} />
          </span>
          <span className="tnum w-28 shrink-0 text-right font-mono text-xs">
            {fmtNum(r.views)} <span className="text-muted">· {r.posts}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
