"use client";

import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { Badge, Button, Card, Dot, PageHeader, PlatformBadge, Toggle, cx } from "@/components/ui";
import Link from "next/link";
import { GROUPS, PLATFORMS, accountKpis, type Platform } from "@/lib/data";
import { useStore } from "@/lib/store";

export default function Accounts() {
  const { accounts, toggleAccountPaused, notify } = useStore();
  const [platform, setPlatform] = useState<Platform | "all" | "reconnect">("all");
  const [group, setGroup] = useState<string>("all");

  const counts = useMemo(() => {
    const m = new Map<Platform, number>();
    accounts.forEach((a) => m.set(a.platform, (m.get(a.platform) ?? 0) + 1));
    return m;
  }, [accounts]);

  const list = accounts.filter(
    (a) => (platform === "all" || (platform === "reconnect" ? a.status === "reconnect" : a.platform === platform)) && (group === "all" || a.group === group),
  );

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Accounts"
        description="Every social account you publish to. Each keeps its own login, time zone, posting hours, language and daily cap."
        actions={
          <Button variant="primary" onClick={() => notify("Pick a platform, then log in to that account with its own email (prototype)")}>
            <Plus size={16} /> Connect account
          </Button>
        }
      />

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <Chip on={platform === "all"} onClick={() => setPlatform("all")}>All {accounts.length}</Chip>
          {(Object.keys(PLATFORMS) as Platform[]).map((p) =>
            counts.get(p) ? (
              <Chip key={p} on={platform === p} onClick={() => setPlatform(p)}>
                {PLATFORMS[p].label} {counts.get(p)}
              </Chip>
            ) : null,
          )}
          <Chip on={platform === "reconnect"} onClick={() => setPlatform("reconnect")}>
            Needs reconnect {accounts.filter((a) => a.status === "reconnect").length}
          </Chip>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">Group</span>
          <select id="group-filter" value={group} onChange={(e) => setGroup(e.target.value)} className="rounded border border-line bg-surface px-2 py-1">
            <option value="all">All groups</option>
            {GROUPS.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>
      </div>

      <Card padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-line text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                <th className="px-5 py-2.5 font-medium">Account</th>
                <th className="px-3 py-2.5 font-medium">Group</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 text-right font-medium">Today</th>
                <th className="px-3 py-2.5 text-right font-medium">Views 2wk</th>
                <th className="px-3 py-2.5 text-right font-medium">Watched</th>
                <th className="px-3 py-2.5 font-medium">Next post</th>
                <th className="px-3 py-2.5 font-medium">Language · zone</th>
                <th className="px-5 py-2.5 text-right font-medium">Posting</th>
              </tr>
            </thead>
            <tbody>
              {list.map((a) => (
                <tr key={a.id} className="border-b border-line last:border-0">
                  <td className="px-5 py-2.5">
                    <span className="flex items-center gap-2">
                      <PlatformBadge platform={a.platform} />
                      <Link href={`/accounts/${a.id}`} className="font-medium hover:text-accent hover:underline">{a.handle}</Link>
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge tone="accent">{a.group}</Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="flex items-center gap-1.5">
                      <Dot tone={a.status === "connected" ? "ok" : a.status === "reconnect" ? "warn" : "off"} />
                      {a.status === "connected" ? "Connected" : a.status === "reconnect" ? (
                        <button className="font-medium text-paid underline" onClick={() => notify(`Reconnect ${a.handle} (prototype)`)}>
                          Reconnect in 3 days
                        </button>
                      ) : (
                        "Paused by you"
                      )}
                    </span>
                  </td>
                  <td className="tnum px-3 py-2.5 text-right font-mono">
                    {a.today} / {PLATFORMS[a.platform].limit}
                  </td>
                  <td className="tnum px-3 py-2.5 text-right font-mono">{(accountKpis(a.id).views7d / 1000).toFixed(1)}k</td>
                  <td className="tnum px-3 py-2.5 text-right font-mono">{accountKpis(a.id).watched}%</td>
                  <td className="tnum px-3 py-2.5 font-mono text-muted">{a.status === "paused" ? "—" : a.next}</td>
                  <td className="px-3 py-2.5 text-muted">
                    {a.language} · <span className="font-mono text-xs">{a.timezone}</span>
                  </td>
                  <td className="px-5 py-2.5">
                    <span className="flex justify-end">
                      <Toggle on={a.status !== "paused"} onChange={() => toggleAccountPaused(a.id)} label={`Posting on ${a.handle}`} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Platform limits clip_star respects">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {(Object.keys(PLATFORMS) as Platform[]).map((p) => (
            <div key={p} className="flex flex-col gap-0.5 rounded border border-line p-3 text-sm">
              <span className="font-semibold">{PLATFORMS[p].label}</span>
              <span className="text-xs text-muted">{PLATFORMS[p].note}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted">Daily caps shown are examples. The real limits are read from each platform when the backend is connected.</p>
      </Card>
    </>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={cx("rounded-full border px-3 py-1 text-xs font-semibold transition-colors", on ? "border-ink bg-ink text-paper" : "border-line text-muted hover:text-ink")}
    >
      {children}
    </button>
  );
}
