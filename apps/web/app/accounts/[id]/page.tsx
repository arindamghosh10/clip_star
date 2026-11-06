"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ChevronLeft } from "lucide-react";
import { PostsTable } from "@/components/PostsTable";
import { Badge, Card, Dot, PageHeader, PlatformBadge, Stat, Tabs, Toggle } from "@/components/ui";
import { PLATFORMS, POSTS, accountKpis } from "@/lib/data";
import { useStore } from "@/lib/store";

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

function Sparkline({ data }: { data: number[] }) {
  const w = 600;
  const h = 120;
  const pad = 8;
  const max = Math.max(...data) * 1.1 || 1;
  const x = (i: number) => pad + (i * (w - pad * 2)) / (data.length - 1);
  const y = (v: number) => h - pad - (v / max) * (h - pad * 2);
  const line = data.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  const last = data.length - 1;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-auto w-full" role="img" aria-label="Daily views for this account, last 14 days">
      <line x1={pad} x2={w - pad} y1={h - pad} y2={h - pad} className="stroke-line" />
      <path d={`${line} L${x(last)},${h - pad} L${x(0)},${h - pad} Z`} className="fill-accent/15" />
      <path d={line} fill="none" strokeWidth={2} className="stroke-accent" />
      <circle cx={x(last)} cy={y(data[last])} r={4} className="fill-accent" />
    </svg>
  );
}

export default function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const { accounts, toggleAccountPaused, notify } = useStore();
  const [tab, setTab] = useState<"all" | "posted" | "upcoming">("all");
  const a = accounts.find((x) => x.id === id);

  if (!a) {
    return (
      <>
        <PageHeader title="Account not found" />
        <Link href="/accounts" className="text-accent">Back to accounts</Link>
      </>
    );
  }

  const kp = accountKpis(a.id);
  const posts = POSTS.filter((p) => p.accountId === a.id)
    .filter((p) => (tab === "all" ? true : tab === "posted" ? p.status === "posted" || p.status === "failed" : p.status === "scheduled" || p.status === "held"))
    .sort((x, y) => y.order - x.order);

  return (
    <>
      <Link href="/accounts" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ChevronLeft size={16} /> Accounts
      </Link>

      <PageHeader
        eyebrow={PLATFORMS[a.platform].label}
        title={a.handle}
        description={`${a.language} · ${a.timezone} · daily cap ${PLATFORMS[a.platform].limit}`}
        actions={
          <label className="flex items-center gap-2 text-sm">
            <Toggle
              on={a.status !== "paused"}
              onChange={() => {
                toggleAccountPaused(a.id);
                notify(a.status === "paused" ? `Posting resumed on ${a.handle}` : `Posting paused on ${a.handle}`);
              }}
              label={`Posting on ${a.handle}`}
            />
            {a.status === "paused" ? "Posting paused" : "Posting on"}
          </label>
        }
      />

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <PlatformBadge platform={a.platform} full />
        <Badge tone="accent">{a.group}</Badge>
        <span className="flex items-center gap-1.5">
          <Dot tone={a.status === "connected" ? "ok" : a.status === "reconnect" ? "warn" : "off"} />
          {a.status === "connected" ? "Connected" : a.status === "reconnect" ? "Reconnect in 3 days" : "Paused by you"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Followers" value={k(kp.followers)} delta={`+${kp.followerGrowth} in 2 weeks`} />
        <Stat label="Views · 2 weeks" value={k(kp.views7d)} />
        <Stat label="Average watched" value={`${kp.watched}%`} />
        <Stat label="Engagement rate" value={`${kp.engagement}%`} />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Posts · 2 weeks" value={String(kp.posts7d)} />
        <Stat label="Scheduled" value={String(kp.scheduled)} />
        <Stat label="Failed" value={String(kp.failed)} />
        <Stat label="Best posting time" value={kp.bestTime} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card title="Daily views · last 14 days">
          <Sparkline data={kp.daily} />
          <p className="mt-1 text-xs text-muted">Sample data.</p>
        </Card>
        <Card title="Best post · 2 weeks">
          {kp.best ? (
            <div className="flex flex-col gap-2 text-sm">
              <span className="text-base font-semibold">{kp.best.clip}</span>
              <span className="font-mono text-xs text-muted">
                Variant {kp.best.variant} · {kp.best.batch} · {kp.best.when}
              </span>
              <dl className="tnum mt-1 grid grid-cols-2 gap-2">
                <Mini k="Views" v={k(kp.best.views)} />
                <Mini k="Watched" v={`${kp.best.watched}%`} />
                <Mini k="Shares" v={String(kp.best.shares)} />
                <Mini k="Follows" v={`+${kp.best.follows}`} />
              </dl>
            </div>
          ) : (
            <p className="text-sm text-muted">Nothing posted yet.</p>
          )}
        </Card>
      </div>

      <Card padded={false} title="Posts from this account" actions={<Link href={`/posts`} className="text-sm font-medium text-accent">All accounts&apos; posts</Link>}>
        <div className="px-5 pt-2">
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { id: "all", label: "All" },
              { id: "posted", label: "Posted" },
              { id: "upcoming", label: "Upcoming" },
            ]}
          />
        </div>
        <PostsTable posts={posts} showAccount={false} />
      </Card>
    </>
  );
}

function Mini({ k: label, v }: { k: string; v: string }) {
  return (
    <div className="rounded border border-line bg-paper p-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-semibold">{v}</dd>
    </div>
  );
}
