"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Badge, Button, Card, PageHeader, PlatformBadge, Tabs, Toggle, cx } from "@/components/ui";
import { VARIATION_MATRIX, type BatchStatus, type Platform, type VariationKind } from "@/lib/data";
import { useStore } from "@/lib/store";

const statusBadge: Record<BatchStatus, { label: string; tone: "gate" | "free" | "neutral" | "accent" }> = {
  awaiting: { label: "Awaiting approval", tone: "gate" },
  running: { label: "Running", tone: "free" },
  disabled: { label: "Disabled", tone: "neutral" },
  finished: { label: "Finished", tone: "accent" },
};

const kindClass: Record<VariationKind, string> = {
  text: "bg-accent-soft text-accent",
  packaging: "bg-paid-soft text-paid",
  edit: "bg-gate-soft text-gate",
  original: "text-muted",
  off: "text-muted/70",
};

const MATRIX_COLS: { p: Platform; n: number }[] = [
  { p: "instagram", n: 10 },
  { p: "facebook", n: 10 },
  { p: "tiktok", n: 10 },
  { p: "youtube", n: 3 },
  { p: "x", n: 2 },
];

type Tab = "batches" | "rules" | "variations";

export default function Publishing() {
  const [tab, setTab] = useState<Tab>("batches");
  const { batches, rules } = useStore();
  return (
    <>
      <PageHeader
        eyebrow="Stage 06 · Publish"
        title="Publishing"
        description="Clips go out in batches. Approve a batch once, switch it off any time, and set rules to build batches for you."
      />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { id: "batches", label: "Batches", count: batches.length },
          { id: "rules", label: "Automation rules", count: rules.length },
          { id: "variations", label: "Variations" },
        ]}
      />
      {tab === "batches" && <BatchesTab />}
      {tab === "rules" && <RulesTab />}
      {tab === "variations" && <VariationsTab />}
    </>
  );
}

function BatchesTab() {
  const { batches, setBatchStatus, notify } = useStore();
  return (
    <div className="flex flex-col gap-3">
      {batches.map((b) => {
        const st = statusBadge[b.status];
        const pct = Math.round((b.posted / b.posts) * 100);
        return (
          <Card key={b.id} className={cx(b.status === "awaiting" && "border-gate/40", b.status === "disabled" && "opacity-80")}>
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
              <div className="flex min-w-0 flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-muted">{b.id}</span>
                  <h3 className="font-semibold">{b.name}</h3>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>
                <div className="tnum flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
                  <span>{b.clips} clips</span>
                  <span>{b.accounts} accounts</span>
                  <span>{b.posts} posts</span>
                  <span>{b.window}</span>
                  <span>Variations: {b.variations}</span>
                </div>
                {b.status !== "awaiting" && (
                  <div className="flex items-center gap-2 text-xs text-muted">
                    <div className="h-1.5 w-40 overflow-hidden rounded-full bg-line">
                      <div className="h-full bg-free" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="tnum font-mono">
                      {b.posted} of {b.posts} posted
                    </span>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {b.status === "awaiting" && (
                  <>
                    <Button
                      variant="primary"
                      onClick={() => {
                        setBatchStatus(b.id, "running");
                        notify(`Batch ${b.id} approved · ${b.posts} posts scheduled`);
                      }}
                    >
                      Approve batch
                    </Button>
                    <Button onClick={() => notify("Batch review opens here: every post, account and time")}>Review posts</Button>
                  </>
                )}
                {(b.status === "running" || b.status === "disabled") && (
                  <label className="flex items-center gap-2 text-sm">
                    <Toggle
                      on={b.status === "running"}
                      label={`Batch ${b.id} on or off`}
                      onChange={() => {
                        const next = b.status === "running" ? "disabled" : "running";
                        setBatchStatus(b.id, next);
                        notify(next === "disabled" ? `Batch ${b.id} disabled · ${b.posts - b.posted} posts held` : `Batch ${b.id} enabled · resumes at next open slot`);
                      }}
                    />
                    {b.status === "running" ? "On" : "Off"}
                  </label>
                )}
              </div>
            </div>
          </Card>
        );
      })}
      <p className="text-sm text-muted">Disabling a batch holds every post that hasn&apos;t gone out yet. Enabling it picks up from the next open slot. Single posts can be switched off from the calendar.</p>
    </div>
  );
}

function RulesTab() {
  const { rules, toggleRule, notify } = useStore();
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button variant="primary" onClick={() => notify("Rule builder opens here (prototype)")}>
          <Plus size={16} /> New rule
        </Button>
      </div>
      {rules.map((r) => (
        <Card
          key={r.id}
          title={r.name}
          actions={
            <label className="flex items-center gap-2 text-sm">
              <Toggle on={r.enabled} onChange={() => toggleRule(r.id)} label={`Rule ${r.name} on or off`} />
              {r.enabled ? "On" : "Off"}
            </label>
          }
        >
          <dl className="flex flex-col divide-y divide-line text-sm">
            <RuleLine k="When" v={[r.when]} />
            <RuleLine k="Post to" v={r.groups} />
            <RuleLine k="Pace" v={[r.pace, r.hours]} />
            <RuleLine k="Spacing" v={[r.spacing]} />
            <RuleLine k="Variations" v={[r.variations]} />
            <RuleLine k="Approval" v={[r.approval]} />
          </dl>
        </Card>
      ))}
    </div>
  );
}

function RuleLine({ k, v }: { k: string; v: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      <dt className="w-24 shrink-0 font-mono text-[11px] uppercase tracking-wider text-muted">{k}</dt>
      <dd className="flex flex-wrap gap-1.5">
        {v.map((x) => (
          <span key={x} className="rounded border border-line bg-paper px-2 py-0.5">
            {x}
          </span>
        ))}
      </dd>
    </div>
  );
}

function VariationsTab() {
  return (
    <Card title="Variation matrix · batch B-0412" padded={false}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="px-5 py-2.5 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">Clip</th>
              {MATRIX_COLS.map((c) => (
                <th key={c.p} className="px-3 py-2.5 text-center">
                  <span className="inline-flex items-center gap-1">
                    <PlatformBadge platform={c.p} /> <span className="font-mono text-xs text-muted">×{c.n}</span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {VARIATION_MATRIX.map((row) => (
              <tr key={row.clip} className="border-b border-line last:border-0">
                <td className="px-5 py-3 font-medium">{row.clip}</td>
                {MATRIX_COLS.map((c) => {
                  const cell = row.cells[c.p];
                  return (
                    <td key={c.p} className="px-3 py-3 text-center">
                      {cell && <span className={cx("rounded px-1.5 py-0.5 font-mono text-xs", kindClass[cell.kind])}>{cell.label}</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-line px-5 py-3 text-xs text-muted">
        <span><span className={cx("rounded px-1.5 py-0.5 font-mono", kindClass.text)}>text</span> title, caption, hashtags, language</span>
        <span><span className={cx("rounded px-1.5 py-0.5 font-mono", kindClass.packaging)}>packaging</span> hook text, cover, caption style</span>
        <span><span className={cx("rounded px-1.5 py-0.5 font-mono", kindClass.edit)}>edit</span> start point, length, opening line</span>
        <span>Variations are optional and set per rule or per batch.</span>
      </div>
    </Card>
  );
}
