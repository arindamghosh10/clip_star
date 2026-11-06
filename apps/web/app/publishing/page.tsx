"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Plus, Trash2, X } from "lucide-react";
import { LivePostsTable } from "@/components/LivePostsTable";
import { Badge, Button, Card, EmptyNote, PageHeader, PlatformBadge, Tabs, Toggle, cx } from "@/components/ui";
import { PLATFORM_RULES, api, fmtTime, type ApiBatch, type BatchBody, type BatchPreview, type PlatformId } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const statusBadge: Record<ApiBatch["status"], { label: string; tone: "gate" | "free" | "neutral" | "accent" }> = {
  awaiting: { label: "Awaiting approval", tone: "gate" },
  running: { label: "Running", tone: "free" },
  disabled: { label: "Disabled", tone: "neutral" },
  finished: { label: "Finished", tone: "accent" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

type Tab = "batches" | "new" | "rules";

export default function Publishing() {
  const [tab, setTab] = useState<Tab>("batches");
  const batches = usePoll(api.batches, { intervalMs: 5000 });
  const rules = usePoll(api.rules, { intervalMs: 30000 });
  return (
    <>
      <PageHeader eyebrow="Stage 06 · Publish" title="Publishing" description="Clips go out in batches. Approve a batch once, switch it off any time, and let rules build batches for you." />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { id: "batches", label: "Batches", count: batches.data?.length },
          { id: "new", label: "New batch" },
          { id: "rules", label: "Automation rules", count: rules.data?.length },
        ]}
      />
      {tab === "batches" && <Batches data={batches.data} error={batches.error} refresh={batches.refresh} onNew={() => setTab("new")} />}
      {tab === "new" && (
        <NewBatch
          onCreated={() => {
            batches.refresh();
            setTab("batches");
          }}
        />
      )}
      {tab === "rules" && <Rules data={rules.data} refresh={rules.refresh} />}
    </>
  );
}

function Batches({ data, error, refresh, onNew }: { data?: ApiBatch[]; error: string | null; refresh: () => void; onNew: () => void }) {
  const { notify } = useStore();
  const [open, setOpen] = useState<string | null>(null);
  async function act(b: ApiBatch, action: "approve" | "disable" | "enable" | "cancel", ok: string) {
    try {
      await api.batchAction(b.id, action);
      notify(ok);
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }
  if (error) return <p className="text-sm text-rec">{error}</p>;
  if (!data) return <p className="text-sm text-muted">Loading…</p>;
  if (!data.length)
    return (
      <EmptyNote>
        No batches yet.{" "}
        <button className="text-accent underline" onClick={onNew}>
          Create one
        </button>{" "}
        from approved clips, or add an automation rule.
      </EmptyNote>
    );
  return (
    <div className="flex flex-col gap-3">
      {data.map((b) => {
        const st = statusBadge[b.status];
        const pct = b.posts ? Math.round((b.posted / b.posts) * 100) : 0;
        return (
          <Card key={b.id} className={cx(b.status === "awaiting" && "border-gate/40")}>
            <div className="flex flex-col gap-3">
              <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                <div className="flex min-w-0 flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold">{b.name}</h3>
                    <Badge tone={st.tone}>{st.label}</Badge>
                    {b.origin !== "manual" && <Badge>from a rule</Badge>}
                  </div>
                  <div className="tnum flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
                    <span>{b.clips} clips</span>
                    <span>{b.accounts} accounts</span>
                    <span>{b.posts} posts</span>
                    <span>Versions: {b.variations === "ab" ? "A/B" : "one"}</span>
                    <span>Created {fmtTime(b.created_at)}</span>
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
                    <Button variant="primary" onClick={() => act(b, "approve", `Approved · ${b.posts} posts scheduled`)}>
                      Approve batch
                    </Button>
                  )}
                  {(b.status === "running" || b.status === "disabled") && (
                    <label className="flex items-center gap-2 text-sm">
                      <Toggle
                        on={b.status === "running"}
                        label={`Batch ${b.name} on or off`}
                        onChange={() => act(b, b.status === "running" ? "disable" : "enable", b.status === "running" ? "Batch disabled; posts held" : "Batch enabled")}
                      />
                      {b.status === "running" ? "On" : "Off"}
                    </label>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => setOpen(open === b.id ? null : b.id)}>
                    {open === b.id ? "Hide posts" : "Review posts"}
                  </Button>
                  {!["finished", "cancelled"].includes(b.status) && (
                    <Button size="sm" variant="ghost" onClick={() => act(b, "cancel", "Batch cancelled")}>
                      Cancel batch
                    </Button>
                  )}
                </div>
              </div>
              {b.warnings.length > 0 && (
                <ul className="flex flex-col gap-1 rounded bg-paid-soft p-3 text-xs text-paid">
                  {b.warnings.slice(0, 5).map((w) => (
                    <li key={w} className="flex items-start gap-2">
                      <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {w}
                    </li>
                  ))}
                </ul>
              )}
              {open === b.id && (
                <div className="-mx-5 -mb-5 border-t border-line">
                  <LivePostsTable filter={{ batch_id: b.id }} />
                </div>
              )}
            </div>
          </Card>
        );
      })}
      <p className="text-sm text-muted">Disabling a batch holds every post that hasn&apos;t gone out. Enabling it continues from the next slot. Single posts can be cancelled from Posts or the Calendar.</p>
    </div>
  );
}

function localInput(d: Date) {
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
}

function NewBatch({ onCreated }: { onCreated: () => void }) {
  const { notify } = useStore();
  const clips = usePoll(() => api.clips({ status: "approved" }), { intervalMs: 30000 });
  const accounts = usePoll(api.accounts, { intervalMs: 30000 });
  const [pickedClips, setPickedClips] = useState<Set<string>>(new Set());
  const [pickedAccounts, setPickedAccounts] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [start, setStart] = useState(localInput(new Date(Date.now() + 10 * 60000)));
  const [spacing, setSpacing] = useState(45);
  const [variations, setVariations] = useState<"off" | "ab">("off");
  const [preview, setPreview] = useState<BatchPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const groups = useMemo(() => {
    const m = new Map<string, string[]>();
    (accounts.data ?? []).forEach((a) => m.set(a.group_name || "No group", [...(m.get(a.group_name || "No group") ?? []), a.id]));
    return m;
  }, [accounts.data]);

  const body = (): BatchBody => ({
    name: name.trim() || `Batch ${new Date().toLocaleDateString()}`,
    clip_ids: [...pickedClips],
    account_ids: [...pickedAccounts],
    groups: [],
    start_at: new Date(start).toISOString(),
    spacing_minutes: spacing,
    variations,
  });
  const toggle = (set: Set<string>, id: string, fn: (s: Set<string>) => void) => {
    const n = new Set(set);
    if (n.has(id)) n.delete(id);
    else n.add(id);
    fn(n);
    setPreview(null);
  };

  async function doPreview() {
    setErr(null);
    setBusy(true);
    try {
      setPreview(await api.previewBatch(body()));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function create() {
    setErr(null);
    setBusy(true);
    try {
      const b = await api.createBatch(body());
      notify(`Batch created with ${b.posts} posts. Approve it to start.`);
      onCreated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={`1 · Approved clips (${pickedClips.size} picked)`}>
        {!clips.data?.length ? (
          <EmptyNote>No approved clips yet. Approve clips on the Clips screen first.</EmptyNote>
        ) : (
          <ul className="flex max-h-80 flex-col gap-1 overflow-y-auto text-sm">
            {clips.data.map((c) => (
              <li key={c.id}>
                <label className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-paper">
                  <input type="checkbox" checked={pickedClips.has(c.id)} onChange={() => toggle(pickedClips, c.id, setPickedClips)} />
                  <span className="font-mono text-xs text-muted">{c.score}</span>
                  <span className="min-w-0 flex-1 truncate">{c.title}</span>
                  <span className="font-mono text-xs text-muted">{c.variants.map((v) => v.id).join("/")}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={`2 · Accounts (${pickedAccounts.size} picked)`}>
        {!accounts.data?.length ? (
          <EmptyNote>No accounts yet. Add or connect accounts first.</EmptyNote>
        ) : (
          <div className="flex max-h-80 flex-col gap-3 overflow-y-auto text-sm">
            {[...groups.entries()].map(([g, ids]) => {
              const all = ids.every((i) => pickedAccounts.has(i));
              return (
                <div key={g} className="flex flex-col gap-1">
                  <label className="flex items-center gap-2 font-semibold">
                    <input
                      type="checkbox"
                      checked={all}
                      onChange={() => {
                        const n = new Set(pickedAccounts);
                        ids.forEach((i) => (all ? n.delete(i) : n.add(i)));
                        setPickedAccounts(n);
                        setPreview(null);
                      }}
                    />
                    {g} <span className="font-normal text-muted">({ids.length})</span>
                  </label>
                  {ids.map((id) => {
                    const a = accounts.data!.find((x) => x.id === id)!;
                    return (
                      <label key={id} className="ml-5 flex items-center gap-2 rounded px-2 py-1 hover:bg-paper">
                        <input type="checkbox" checked={pickedAccounts.has(id)} onChange={() => toggle(pickedAccounts, id, setPickedAccounts)} />
                        <PlatformBadge platform={a.platform} /> {a.handle}
                        {a.status !== "connected" && <Badge tone="paid">{a.status}</Badge>}
                      </label>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
      </Card>
      <Card title="3 · When and how" className="lg:col-span-2">
        <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <label htmlFor="b-name" className="flex flex-col gap-1">
            <span className="text-xs text-muted">Batch name</span>
            <input id="b-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Ep. 113 clips" className="rounded border border-line bg-paper px-3 py-2" />
          </label>
          <label htmlFor="b-start" className="flex flex-col gap-1">
            <span className="text-xs text-muted">Start (your local time)</span>
            <input id="b-start" type="datetime-local" value={start} onChange={(e) => (setStart(e.target.value), setPreview(null))} className="rounded border border-line bg-paper px-3 py-2" />
          </label>
          <label htmlFor="b-spacing" className="flex flex-col gap-1">
            <span className="text-xs text-muted">Minutes between accounts for the same clip</span>
            <input id="b-spacing" type="number" min={0} max={1440} value={spacing} onChange={(e) => (setSpacing(Math.max(0, Number(e.target.value) || 0)), setPreview(null))} className="rounded border border-line bg-paper px-3 py-2" />
          </label>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted">Versions</span>
            <div className="flex gap-2">
              {(["off", "ab"] as const).map((v) => (
                <button key={v} onClick={() => (setVariations(v), setPreview(null))} className={cx("rounded border px-3 py-2", variations === v ? "border-accent bg-accent-soft" : "border-line")}>
                  {v === "off" ? "Same version" : "Rotate A/B"}
                </button>
              ))}
            </div>
          </div>
        </div>
        <p className="mt-3 text-xs text-muted">Each account still posts only inside its own posting hours and daily limit, in its own time zone.</p>
        {err && (
          <p role="alert" className="mt-3 flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {err}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button disabled={busy || !pickedClips.size || !pickedAccounts.size} onClick={doPreview}>
            Preview schedule
          </Button>
          <Button variant="primary" disabled={busy || !preview?.posts.length} onClick={create}>
            Create batch ({preview?.posts.length ?? 0} posts)
          </Button>
        </div>
      </Card>
      {preview && (
        <Card title={`Schedule preview · ${preview.posts.length} posts`} className="lg:col-span-2" padded={false}>
          {(preview.warnings.length > 0 || preview.skipped.length > 0) && (
            <ul className="flex flex-col gap-1 border-b border-line bg-paid-soft px-5 py-3 text-xs text-paid">
              {[...preview.warnings, ...preview.skipped].map((w) => (
                <li key={w} className="flex items-start gap-2">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {w}
                </li>
              ))}
            </ul>
          )}
          <div className="max-h-96 overflow-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-line text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                  <th className="px-5 py-2 font-medium">Your time</th>
                  <th className="px-3 py-2 font-medium">Account&apos;s local time</th>
                  <th className="px-3 py-2 font-medium">Account</th>
                  <th className="px-3 py-2 font-medium">Clip</th>
                  <th className="px-5 py-2 font-medium">Version</th>
                </tr>
              </thead>
              <tbody>
                {preview.posts.map((p, i) => (
                  <tr key={i} className="border-b border-line last:border-0">
                    <td className="px-5 py-2 font-mono text-xs">{fmtTime(p.at)}</td>
                    <td className="px-3 py-2 font-mono text-xs text-muted">{new Date(p.at).toLocaleString(undefined, { timeZone: p.timezone, weekday: "short", hour: "2-digit", minute: "2-digit" })}</td>
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-2">
                        <PlatformBadge platform={p.platform} /> {p.handle}
                      </span>
                    </td>
                    <td className="px-3 py-2">{p.clip}</td>
                    <td className="px-5 py-2 font-mono text-xs">{p.variant}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function Rules({ data, refresh }: { data?: import("@/lib/api").ApiRule[]; refresh: () => void }) {
  const { notify } = useStore();
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  const groups = Array.from(new Set((accounts.data ?? []).map((a) => a.group_name).filter(Boolean)));
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", min_score: 80, groups: [] as string[], platforms: [] as PlatformId[], start_delay_minutes: 60, variations: "off" as "off" | "ab" });

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      notify(ok);
      refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">When a video finishes processing, each rule that is on builds a batch from its clips. Batches from rules still wait for your approval.</p>
      <div className="flex justify-end">
        <Button variant="primary" onClick={() => setAdding(!adding)}>
          {adding ? <X size={16} /> : <Plus size={16} />} {adding ? "Close" : "New rule"}
        </Button>
      </div>
      {adding && (
        <Card title="New rule">
          <div className="flex flex-col gap-3 text-sm">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label htmlFor="r-name" className="flex flex-col gap-1">
                <span className="text-xs text-muted">Name</span>
                <input id="r-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Top clips to English accounts" className="rounded border border-line bg-paper px-3 py-2" />
              </label>
              <label htmlFor="r-score" className="flex flex-col gap-1">
                <span className="text-xs text-muted">Clips scoring at least</span>
                <input id="r-score" type="number" min={0} max={100} value={f.min_score} onChange={(e) => setF({ ...f, min_score: Number(e.target.value) || 0 })} className="rounded border border-line bg-paper px-3 py-2" />
              </label>
              <label htmlFor="r-delay" className="flex flex-col gap-1">
                <span className="text-xs text-muted">Start this many minutes later</span>
                <input id="r-delay" type="number" min={0} max={10080} value={f.start_delay_minutes} onChange={(e) => setF({ ...f, start_delay_minutes: Number(e.target.value) || 0 })} className="rounded border border-line bg-paper px-3 py-2" />
              </label>
              <label htmlFor="r-var" className="flex flex-col gap-1">
                <span className="text-xs text-muted">Versions</span>
                <select id="r-var" value={f.variations} onChange={(e) => setF({ ...f, variations: e.target.value as "off" | "ab" })} className="rounded border border-line bg-surface px-2 py-2">
                  <option value="off">Same version</option>
                  <option value="ab">Rotate A/B</option>
                </select>
              </label>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted">Post to these groups (none picked = all accounts)</span>
              <div className="flex flex-wrap gap-2">
                {groups.map((g) => (
                  <button key={g} aria-pressed={f.groups.includes(g)} onClick={() => setF({ ...f, groups: f.groups.includes(g) ? f.groups.filter((x) => x !== g) : [...f.groups, g] })} className={cx("rounded-full border px-3 py-1 text-xs font-semibold", f.groups.includes(g) ? "border-ink bg-ink text-paper" : "border-line text-muted")}>
                    {g}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted">Only these platforms (none picked = all)</span>
              <div className="flex flex-wrap gap-2">
                {(Object.keys(PLATFORM_RULES) as PlatformId[]).map((p) => (
                  <button key={p} aria-pressed={f.platforms.includes(p)} onClick={() => setF({ ...f, platforms: f.platforms.includes(p) ? f.platforms.filter((x) => x !== p) : [...f.platforms, p] })} className={cx("rounded-full border px-3 py-1 text-xs font-semibold", f.platforms.includes(p) ? "border-ink bg-ink text-paper" : "border-line text-muted")}>
                    {PLATFORM_RULES[p].label}
                  </button>
                ))}
              </div>
            </div>
            <Button
              variant="primary"
              className="self-start"
              disabled={!f.name.trim()}
              onClick={() =>
                act(async () => {
                  await api.createRule({ name: f.name.trim(), enabled: true, config: { min_score: f.min_score, groups: f.groups, platforms: f.platforms, start_delay_minutes: f.start_delay_minutes, variations: f.variations } });
                  setAdding(false);
                }, "Rule saved")
              }
            >
              Save rule
            </Button>
          </div>
        </Card>
      )}
      {!data?.length && !adding && <EmptyNote>No rules yet.</EmptyNote>}
      {data?.map((r) => (
        <Card
          key={r.id}
          title={r.name}
          actions={
            <span className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-sm">
                <Toggle on={r.enabled} onChange={() => act(() => api.updateRule(r.id, { enabled: !r.enabled }), r.enabled ? "Rule off" : "Rule on")} label={`Rule ${r.name}`} />
                {r.enabled ? "On" : "Off"}
              </label>
              <button aria-label={`Delete rule ${r.name}`} className="rounded p-1 text-muted hover:bg-paper hover:text-rec" onClick={() => act(() => api.deleteRule(r.id), "Rule deleted")}>
                <Trash2 size={16} />
              </button>
            </span>
          }
        >
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <Rl k="Clips scoring ≥" v={String(r.config.min_score ?? 0)} />
            <Rl k="Groups" v={r.config.groups?.length ? r.config.groups.join(", ") : "All accounts"} />
            <Rl k="Platforms" v={r.config.platforms?.length ? r.config.platforms.map((p) => PLATFORM_RULES[p]?.label ?? p).join(", ") : "All"} />
            <Rl k="Starts after" v={`${r.config.start_delay_minutes ?? 60} min`} />
            <Rl k="Versions" v={r.config.variations === "ab" ? "Rotate A/B" : "Same version"} />
          </dl>
        </Card>
      ))}
    </div>
  );
}

function Rl({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2">
      <dt className="text-muted">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}
