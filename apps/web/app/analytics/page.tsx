"use client";

import { Badge, Button, Card, PageHeader, PlatformBadge, Stat } from "@/components/ui";
import { DAILY_VIEWS, INSIGHTS, PERFORMANCE } from "@/lib/data";
import { useStore } from "@/lib/store";

function ViewsChart() {
  const w = 640;
  const h = 180;
  const pad = { l: 40, r: 12, t: 12, b: 24 };
  const max = 30000;
  const x = (i: number) => pad.l + (i * (w - pad.l - pad.r)) / (DAILY_VIEWS.length - 1);
  const y = (v: number) => pad.t + (1 - v / max) * (h - pad.t - pad.b);
  const line = DAILY_VIEWS.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const area = `${line} L${x(DAILY_VIEWS.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const ticks = [0, 10000, 20000, 30000];
  const last = DAILY_VIEWS.length - 1;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-auto w-full" role="img" aria-label="Daily views over the last 14 days">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} className="stroke-line" strokeWidth={1} />
          <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="fill-muted font-mono text-[10px]">
            {t / 1000}k
          </text>
        </g>
      ))}
      <path d={area} className="fill-accent/15" />
      <path d={line} className="stroke-accent" fill="none" strokeWidth={2} />
      <circle cx={x(last)} cy={y(DAILY_VIEWS[last])} r={4} className="fill-accent" />
      <text x={pad.l} y={h - 6} className="fill-muted font-mono text-[10px]">14 days ago</text>
      <text x={w - pad.r} y={h - 6} textAnchor="end" className="fill-muted font-mono text-[10px]">Today</text>
    </svg>
  );
}

export default function Analytics() {
  const { notify } = useStore();
  return (
    <>
      <PageHeader eyebrow="Stages 08–09 · Measure & learn" title="Analytics" description="Stats are pulled 1 hour, 1 day, 3 days and 7 days after each post, and linked back to the moment, hook, length and engine that made the clip." />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Views · 7 days" value="148.5k" delta="+38%" />
        <Stat label="Average watched" value="51%" delta="+6 pts" />
        <Stat label="Shares" value="3,138" delta="+41%" />
        <Stat label="Follows gained" value="+976" delta="+22%" />
      </div>

      <Card title="Daily views · all accounts">
        <ViewsChart />
        <p className="mt-2 text-xs text-muted">Sample data.</p>
      </Card>

      <Card title="Top clips" padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-b border-line text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                <th className="px-5 py-2.5 font-medium">Clip</th>
                <th className="px-3 py-2.5 font-medium">Platform</th>
                <th className="px-3 py-2.5 text-right font-medium">Views</th>
                <th className="px-3 py-2.5 text-right font-medium">Watched</th>
                <th className="px-3 py-2.5 text-right font-medium">Shares</th>
                <th className="px-5 py-2.5 text-right font-medium">Follows</th>
              </tr>
            </thead>
            <tbody className="tnum">
              {[...PERFORMANCE].sort((a, b) => b.views - a.views).map((p) => (
                <tr key={p.clip} className="border-b border-line last:border-0">
                  <td className="px-5 py-2.5 font-medium">{p.clip}</td>
                  <td className="px-3 py-2.5"><PlatformBadge platform={p.platform} full /></td>
                  <td className="px-3 py-2.5 text-right font-mono">{p.views.toLocaleString("en-US")}</td>
                  <td className="px-3 py-2.5 text-right font-mono">{p.watched}%</td>
                  <td className="px-3 py-2.5 text-right font-mono">{p.shares.toLocaleString("en-US")}</td>
                  <td className="px-5 py-2.5 text-right font-mono">+{p.follows}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Insights and suggestions" actions={<span className="text-xs text-muted">Weekly report · Mon 09:00</span>}>
        <div className="grid gap-3 md:grid-cols-2">
          {INSIGHTS.map((i) => (
            <div key={i.title} className="flex flex-col gap-1.5 rounded border border-line p-4 text-sm">
              <Badge tone={i.kind === "do" ? "free" : i.kind === "avoid" ? "rec" : "accent"} className="self-start">
                {i.kind === "do" ? "Do more" : i.kind === "avoid" ? "Do less" : "Idea"}
              </Badge>
              <span className="font-semibold">{i.title}</span>
              <span className="text-muted">{i.body}</span>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => notify("Re-clipping 3 old episodes with your best pattern (prototype)")}>Re-clip 3 old episodes</Button>
          <Button onClick={() => notify("Report export (prototype)")}>Export report</Button>
        </div>
      </Card>
    </>
  );
}
