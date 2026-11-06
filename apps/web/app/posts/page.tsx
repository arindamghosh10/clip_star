"use client";

import { useMemo, useState, type ChangeEvent, type ReactNode } from "react";
import { PostsTable } from "@/components/PostsTable";
import { Button, Card, PageHeader, Stat } from "@/components/ui";
import { ACCOUNTS, BATCH_IDS, CLIP_NAMES, GROUPS, PLATFORMS, POSTS, type Platform, type PostStatus } from "@/lib/data";

type Filters = { account: string; platform: string; group: string; clip: string; batch: string; status: string };
const EMPTY: Filters = { account: "all", platform: "all", group: "all", clip: "all", batch: "all", status: "all" };

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

export default function Posts() {
  const [f, setF] = useState<Filters>(EMPTY);
  const [sort, setSort] = useState<"recent" | "views" | "watched">("recent");

  const list = useMemo(() => {
    const out = POSTS.filter((p) => {
      const a = ACCOUNTS.find((x) => x.id === p.accountId)!;
      return (
        (f.account === "all" || p.accountId === f.account) &&
        (f.platform === "all" || a.platform === f.platform) &&
        (f.group === "all" || a.group === f.group) &&
        (f.clip === "all" || p.clip === f.clip) &&
        (f.batch === "all" || p.batch === f.batch) &&
        (f.status === "all" || p.status === f.status)
      );
    });
    if (sort === "views") return out.sort((a, b) => b.views - a.views);
    if (sort === "watched") return out.sort((a, b) => b.watched - a.watched);
    return out.sort((a, b) => b.order - a.order);
  }, [f, sort]);

  const live = list.filter((p) => p.status === "posted");
  const views = live.reduce((n, p) => n + p.views, 0);
  const watched = live.length ? Math.round(live.reduce((n, p) => n + p.watched, 0) / live.length) : 0;
  const follows = live.reduce((n, p) => n + p.follows, 0);
  const set = (key: keyof Filters) => (e: ChangeEvent<HTMLSelectElement>) => setF({ ...f, [key]: e.target.value });
  const active = Object.entries(f).filter(([, v]) => v !== "all").length;

  return (
    <>
      <PageHeader
        eyebrow="Stage 06–08"
        title="Posts"
        description="Every post from every account: what went out, what's scheduled, and how each one is doing. Filter to see exactly which account posted what."
      />

      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <Select id="f-account" label="Account" value={f.account} onChange={set("account")}>
            <option value="all">All accounts</option>
            {ACCOUNTS.map((a) => (
              <option key={a.id} value={a.id}>
                {PLATFORMS[a.platform].short} · {a.handle}
              </option>
            ))}
          </Select>
          <Select id="f-platform" label="Platform" value={f.platform} onChange={set("platform")}>
            <option value="all">All platforms</option>
            {(Object.keys(PLATFORMS) as Platform[])
              .filter((p) => ACCOUNTS.some((a) => a.platform === p))
              .map((p) => (
                <option key={p} value={p}>
                  {PLATFORMS[p].label}
                </option>
              ))}
          </Select>
          <Select id="f-group" label="Group" value={f.group} onChange={set("group")}>
            <option value="all">All groups</option>
            {GROUPS.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </Select>
          <Select id="f-clip" label="Clip" value={f.clip} onChange={set("clip")}>
            <option value="all">All clips</option>
            {CLIP_NAMES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
          <Select id="f-batch" label="Batch" value={f.batch} onChange={set("batch")}>
            <option value="all">All batches</option>
            {BATCH_IDS.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </Select>
          <Select id="f-status" label="Status" value={f.status} onChange={set("status")}>
            <option value="all">Any status</option>
            {(["posted", "scheduled", "failed", "held"] as PostStatus[]).map((s) => (
              <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>
            ))}
          </Select>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="text-muted">
            {list.length} posts{active ? ` · ${active} filter${active > 1 ? "s" : ""} on` : ""}
          </span>
          <div className="flex items-center gap-2">
            <label htmlFor="f-sort" className="text-muted">Sort</label>
            <select id="f-sort" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="rounded border border-line bg-surface px-2 py-1">
              <option value="recent">Newest first</option>
              <option value="views">Most views</option>
              <option value="watched">Best watched %</option>
            </select>
            {active > 0 && (
              <Button size="sm" variant="ghost" onClick={() => setF(EMPTY)}>
                Clear filters
              </Button>
            )}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Posted" value={String(live.length)} />
        <Stat label="Views" value={k(views)} />
        <Stat label="Average watched" value={`${watched}%`} />
        <Stat label="Follows gained" value={`+${follows}`} />
      </div>

      <Card padded={false}>
        <PostsTable posts={list} />
      </Card>
    </>
  );
}

function Select({ id, label, value, onChange, children }: { id: string; label: string; value: string; onChange: (e: ChangeEvent<HTMLSelectElement>) => void; children: ReactNode }) {
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="text-xs text-muted">{label}</span>
      <select id={id} value={value} onChange={onChange} className="w-full min-w-0 rounded border border-line bg-surface px-2 py-1.5">
        {children}
      </select>
    </label>
  );
}
