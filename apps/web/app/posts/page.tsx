"use client";

import { useMemo, useState } from "react";
import { LivePostsTable, type PostFilter } from "@/components/LivePostsTable";
import { Button, Card, PageHeader } from "@/components/ui";
import { PLATFORM_RULES, api, type PlatformId } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

const EMPTY: PostFilter = { account_id: "", platform: "", group: "", status: "", batch_id: "" };

export default function Posts() {
  const [f, setF] = useState<PostFilter>(EMPTY);
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  const batches = usePoll(api.batches, { intervalMs: 60000 });
  const groups = useMemo(() => Array.from(new Set((accounts.data ?? []).map((a) => a.group_name).filter(Boolean))).sort(), [accounts.data]);
  const active = Object.values(f).filter(Boolean).length;
  const set = (k: keyof PostFilter) => (e: React.ChangeEvent<HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  return (
    <>
      <PageHeader eyebrow="Stage 06" title="Posts" description="Every post from every account: what went out, what's waiting, and what needs a look. Filter to see exactly which account posted what." />
      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Sel id="f-account" label="Account" value={f.account_id ?? ""} onChange={set("account_id")}>
            <option value="">All accounts</option>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {PLATFORM_RULES[a.platform].label} · {a.handle}
              </option>
            ))}
          </Sel>
          <Sel id="f-platform" label="Platform" value={f.platform ?? ""} onChange={set("platform")}>
            <option value="">All platforms</option>
            {(Object.keys(PLATFORM_RULES) as PlatformId[]).map((p) => (
              <option key={p} value={p}>
                {PLATFORM_RULES[p].label}
              </option>
            ))}
          </Sel>
          <Sel id="f-group" label="Group" value={f.group ?? ""} onChange={set("group")}>
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </Sel>
          <Sel id="f-batch" label="Batch" value={f.batch_id ?? ""} onChange={set("batch_id")}>
            <option value="">All batches</option>
            {(batches.data ?? []).map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </Sel>
          <Sel id="f-status" label="Status" value={f.status ?? ""} onChange={set("status")}>
            <option value="">Any status</option>
            <option value="published">Posted</option>
            <option value="scheduled">Scheduled</option>
            <option value="held">Waiting for approval</option>
            <option value="unknown">Checking</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </Sel>
        </div>
        {active > 0 && (
          <Button size="sm" variant="ghost" className="mt-3" onClick={() => setF(EMPTY)}>
            Clear {active} filter{active > 1 ? "s" : ""}
          </Button>
        )}
      </Card>
      <Card padded={false}>
        <LivePostsTable filter={Object.fromEntries(Object.entries(f).filter(([, v]) => v))} />
      </Card>
    </>
  );
}

function Sel({ id, label, value, onChange, children }: { id: string; label: string; value: string; onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void; children: React.ReactNode }) {
  return (
    <label htmlFor={id} className="flex min-w-0 flex-col gap-1 text-sm">
      <span className="text-xs text-muted">{label}</span>
      <select id={id} value={value} onChange={onChange} className="w-full min-w-0 rounded border border-line bg-surface px-2 py-1.5">
        {children}
      </select>
    </label>
  );
}
