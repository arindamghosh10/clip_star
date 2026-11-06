"use client";

import Link from "next/link";
import { useState } from "react";
import { ExternalLink } from "lucide-react";
import { fmtNum, type AnalyticsOverview, type Insight, type TopPost } from "@/lib/api";
import { Badge, EmptyNote, PlatformBadge } from "./ui";

/** Daily views by publish day: one series, so no legend; hover a day for exact numbers. */
export function ViewsChart({ series }: { series: AnalyticsOverview["series"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const w = 640;
  const h = 190;
  const pad = { l: 44, r: 8, t: 12, b: 24 };
  const max = niceMax(Math.max(1, ...series.map((d) => d.views)));
  const n = series.length;
  const slot = (w - pad.l - pad.r) / Math.max(n, 1);
  const bw = Math.max(2, Math.min(28, slot - 2));
  const y = (v: number) => pad.t + (1 - v / max) * (h - pad.t - pad.b);
  const ticks = [0, max / 2, max];
  const hd = hover !== null ? series[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-auto w-full" role="img" aria-label={`Views by day posted, last ${n} days`} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} className="stroke-line" strokeWidth={1} />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="fill-muted font-mono text-[10px]">
              {fmtNum(t)}
            </text>
          </g>
        ))}
        {series.map((d, i) => {
          const x = pad.l + i * slot + (slot - bw) / 2;
          const top = y(d.views);
          const bh = Math.max(0, y(0) - top);
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)}>
              <rect x={pad.l + i * slot} y={pad.t} width={slot} height={h - pad.t - pad.b} fill="transparent" />
              {bh > 0 && <path d={roundedTop(x, top, bw, bh, Math.min(4, bw / 2))} className={hover === i ? "fill-accent" : "fill-accent/80"} />}
            </g>
          );
        })}
        <text x={pad.l} y={h - 6} className="fill-muted font-mono text-[10px]">
          {shortDate(series[0]?.date)}
        </text>
        <text x={w - pad.r} y={h - 6} textAnchor="end" className="fill-muted font-mono text-[10px]">
          {shortDate(series[n - 1]?.date)}
        </text>
      </svg>
      {hd && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded border border-line bg-surface px-2.5 py-1.5 text-xs shadow"
          style={{ left: `${(((hover ?? 0) + 0.5) / n) * 100}%`, transform: "translateX(-50%)" }}
        >
          <div className="font-semibold">{shortDate(hd.date)}</div>
          <div className="tnum text-muted">
            {fmtNum(hd.views)} views · {hd.posts} post{hd.posts === 1 ? "" : "s"}
          </div>
        </div>
      )}
    </div>
  );
}

function roundedTop(x: number, y: number, w: number, h: number, r: number) {
  r = Math.min(r, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

function niceMax(v: number) {
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

function shortDate(iso?: string) {
  if (!iso) return "";
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function TopPostsTable({ posts, showAccount = true }: { posts: TopPost[]; showAccount?: boolean }) {
  if (!posts.length) return <div className="p-5"><EmptyNote>No stats yet. The first numbers arrive about an hour after a post goes out.</EmptyNote></div>;
  return (
    <div className="overflow-x-auto">
      <table className={showAccount ? "w-full min-w-[680px] text-sm" : "w-full min-w-[520px] text-sm"}>
        <thead>
          <tr className="border-b border-line text-left font-mono text-[11px] uppercase tracking-wider text-muted">
            <th className="px-5 py-2.5 font-medium">Clip</th>
            {showAccount && <th className="px-3 py-2.5 font-medium">Account</th>}
            <th className="px-3 py-2.5 text-right font-medium">Views</th>
            <th className="px-3 py-2.5 text-right font-medium" title="Views compared with this account's typical post">vs usual</th>
            <th className="px-3 py-2.5 text-right font-medium">Watched</th>
            <th className="px-3 py-2.5 text-right font-medium">Shares</th>
            <th className="px-5 py-2.5 text-right font-medium">Follows</th>
          </tr>
        </thead>
        <tbody className="tnum">
          {posts.map((p) => (
            <tr key={p.post_id} className="border-b border-line last:border-0">
              <td className="px-5 py-2.5">
                <Link href={`/clips/${p.clip_id}`} className="font-medium hover:text-accent">{p.clip_title}</Link>
                <span className="font-mono text-xs text-muted"> · {p.variant}</span>
                {p.remote_url && (
                  <a href={p.remote_url} target="_blank" rel="noreferrer" className="ml-2 inline-flex items-center text-accent" aria-label="Open post">
                    <ExternalLink size={12} />
                  </a>
                )}
              </td>
              {showAccount && <td className="px-3 py-2.5">
                <Link href={`/accounts/${p.account_id}`} className="flex items-center gap-1.5 hover:text-accent">
                  <PlatformBadge platform={p.platform} /> {p.account}
                  {p.practice && <Badge>practice</Badge>}
                </Link>
              </td>}
              <td className="px-3 py-2.5 text-right font-mono">{fmtNum(p.views)}</td>
              <td className="px-3 py-2.5 text-right font-mono">{p.rel != null ? `${p.rel.toFixed(1)}×` : "—"}</td>
              <td className="px-3 py-2.5 text-right font-mono">{p.watch_pct != null ? `${Math.round(p.watch_pct)}%` : "—"}</td>
              <td className="px-3 py-2.5 text-right font-mono">{fmtNum(p.shares)}</td>
              <td className="px-5 py-2.5 text-right font-mono">{p.follows != null ? `+${fmtNum(p.follows)}` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function InsightCard({ i, compact = false }: { i: Insight; compact?: boolean }) {
  return (
    <div className={compact ? "flex flex-col gap-1 rounded bg-accent-soft p-3 text-sm" : "flex flex-col gap-1.5 rounded border border-line p-4 text-sm"}>
      <span className="flex items-center gap-2">
        <Badge tone={i.kind === "do" ? "free" : "rec"}>{i.kind === "do" ? "Do more" : "Do less"}</Badge>
        <span className="font-mono text-[11px] text-muted">{i.n} posts</span>
      </span>
      <span className="font-semibold">{i.title}</span>
      <span className="text-muted">{i.body}</span>
    </div>
  );
}

export function PracticeNote({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <p className="rounded border border-paid/30 bg-paid-soft px-3 py-2 text-xs text-paid">
      These numbers come from practice accounts. They're made up (with clear patterns, so you can try insights and learning) and nothing was really posted.
    </p>
  );
}
