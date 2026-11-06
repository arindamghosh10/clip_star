"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Plus, X } from "lucide-react";
import { Badge, Button, Card, Dot, EmptyNote, PageHeader, PlatformBadge, Toggle, cx } from "@/components/ui";
import { PLATFORM_RULES, api, fmtTime, type ApiAccount, type PlatformId } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const PLATFORMS = Object.keys(PLATFORM_RULES) as PlatformId[];

export default function AccountsPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <Accounts />
    </Suspense>
  );
}

function Accounts() {
  const { notify } = useStore();
  const params = useSearchParams();
  const accounts = usePoll(api.accounts, { intervalMs: 15000 });
  const stats = usePoll(api.accountStats, { intervalMs: 15000 });
  const [platform, setPlatform] = useState<PlatformId | "all" | "attention">("all");
  const [group, setGroup] = useState("all");
  const [adding, setAdding] = useState<null | "connect" | "practice">(null);

  const all = accounts.data ?? [];
  const groups = useMemo(() => Array.from(new Set(all.map((a) => a.group_name).filter(Boolean))).sort(), [all]);
  const attention = all.filter((a) => a.status === "reconnect" || a.last_error);
  const list = all.filter(
    (a) => (platform === "all" || (platform === "attention" ? a.status === "reconnect" || !!a.last_error : a.platform === platform)) && (group === "all" || a.group_name === group),
  );

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      notify(ok);
      accounts.refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }

  async function reconnect(a: ApiAccount) {
    try {
      const { authorize_url } = await api.startConnect(a.platform, a.group_name);
      window.location.href = authorize_url;
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Accounts"
        description="Every social account you publish to. Each keeps its own login, time zone, posting hours and daily limit."
        actions={
          <>
            <Button onClick={() => setAdding("practice")}>Add practice account</Button>
            <Button variant="primary" onClick={() => setAdding("connect")}>
              <Plus size={16} /> Connect account
            </Button>
          </>
        }
      />

      {params.get("connected") && (
        <p role="status" className="flex items-start gap-2 rounded bg-free-soft p-3 text-sm text-free">
          <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> Connected {params.get("connected")}.
        </p>
      )}
      {params.get("error") && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {params.get("error")}
        </p>
      )}
      {accounts.error && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {accounts.error}
        </p>
      )}

      {adding === "connect" && <ConnectPanel groups={groups} onClose={() => setAdding(null)} />}
      {adding === "practice" && (
        <PracticePanel
          groups={groups}
          onClose={() => setAdding(null)}
          onCreated={() => {
            setAdding(null);
            accounts.refresh();
          }}
        />
      )}

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <Chip on={platform === "all"} onClick={() => setPlatform("all")}>
            All {all.length}
          </Chip>
          {PLATFORMS.filter((p) => all.some((a) => a.platform === p)).map((p) => (
            <Chip key={p} on={platform === p} onClick={() => setPlatform(p)}>
              {PLATFORM_RULES[p].label} {all.filter((a) => a.platform === p).length}
            </Chip>
          ))}
          {attention.length > 0 && (
            <Chip on={platform === "attention"} onClick={() => setPlatform("attention")}>
              Needs attention {attention.length}
            </Chip>
          )}
        </div>
        {groups.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label htmlFor="group-filter" className="text-muted">
              Group
            </label>
            <select id="group-filter" value={group} onChange={(e) => setGroup(e.target.value)} className="rounded border border-line bg-surface px-2 py-1">
              <option value="all">All groups</option>
              {groups.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <Card padded={false}>
        {accounts.loading && !accounts.data ? (
          <p className="px-5 py-6 text-sm text-muted">Loading…</p>
        ) : !list.length ? (
          <div className="p-5">
            <EmptyNote>{all.length ? "No accounts match." : "No accounts yet. Connect one through its platform's login, or add a practice account to try publishing safely."}</EmptyNote>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-line text-left font-mono text-[11px] uppercase tracking-wider text-muted">
                  <th className="px-5 py-2.5 font-medium">Account</th>
                  <th className="px-3 py-2.5 font-medium">Group</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5 text-right font-medium">Last 24 h</th>
                  <th className="px-3 py-2.5 text-right font-medium">Waiting</th>
                  <th className="px-3 py-2.5 font-medium">Next post</th>
                  <th className="px-3 py-2.5 font-medium">Hours · zone</th>
                  <th className="px-5 py-2.5 text-right font-medium">Posting</th>
                </tr>
              </thead>
              <tbody>
                {list.map((a) => {
                  const st = stats.data?.[a.id];
                  return (
                    <tr key={a.id} className="border-b border-line last:border-0">
                      <td className="px-5 py-2.5">
                        <span className="flex items-center gap-2">
                          <PlatformBadge platform={a.platform} />
                          <Link href={`/accounts/${a.id}`} className="font-medium hover:text-accent hover:underline">
                            {a.handle}
                          </Link>
                          {a.connection === "simulated" && <Badge>practice</Badge>}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">{a.group_name ? <Badge tone="accent">{a.group_name}</Badge> : <span className="text-muted">—</span>}</td>
                      <td className="px-3 py-2.5">
                        <span className="flex items-center gap-1.5">
                          <Dot tone={a.status === "connected" ? (st?.problems ? "warn" : "ok") : a.status === "reconnect" ? "bad" : "off"} />
                          {a.status === "reconnect" ? (
                            <button className="font-medium text-rec underline" onClick={() => reconnect(a)}>
                              Reconnect
                            </button>
                          ) : a.status === "paused" ? (
                            "Paused"
                          ) : (
                            "Connected"
                          )}
                          {!!st?.problems && <span className="text-xs text-paid">· {st.problems} need a look</span>}
                        </span>
                      </td>
                      <td className="tnum px-3 py-2.5 text-right font-mono">
                        {st?.posted_24h ?? 0} / {a.daily_cap}
                      </td>
                      <td className="tnum px-3 py-2.5 text-right font-mono">{st?.waiting ?? 0}</td>
                      <td className="tnum px-3 py-2.5 font-mono text-xs text-muted">{st?.next_at ? fmtTime(st.next_at) : "—"}</td>
                      <td className="px-3 py-2.5 text-xs text-muted">
                        {a.posting_start}–{a.posting_end} · <span className="font-mono">{a.timezone}</span>
                      </td>
                      <td className="px-5 py-2.5">
                        <span className="flex justify-end">
                          <Toggle
                            on={a.status === "connected"}
                            label={`Posting on ${a.handle}`}
                            onChange={() =>
                              a.status === "reconnect"
                                ? reconnect(a)
                                : act(() => api.updateAccount(a.id, { status: a.status === "paused" ? "connected" : "paused" }), a.status === "paused" ? `Posting resumed on ${a.handle}` : `Posting paused on ${a.handle}`)
                            }
                          />
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-pressed={on} className={cx("rounded-full border px-3 py-1 text-xs font-semibold transition-colors", on ? "border-ink bg-ink text-paper" : "border-line text-muted hover:text-ink")}>
      {children}
    </button>
  );
}

function ConnectPanel({ groups, onClose }: { groups: string[]; onClose: () => void }) {
  const { notify } = useStore();
  const apps = usePoll(api.platforms, { intervalMs: 60000 });
  const [group, setGroup] = useState("");
  async function go(p: PlatformId) {
    try {
      const { authorize_url } = await api.startConnect(p, group);
      window.location.href = authorize_url;
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <Card title="Connect an account" actions={<button aria-label="Close" onClick={onClose} className="rounded p-1 hover:bg-paper"><X size={16} /></button>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">You&apos;ll sign in on the platform with that account&apos;s own login. clip_star stores the access it grants, encrypted, never your password.</p>
        <label htmlFor="connect-group" className="flex max-w-sm flex-col gap-1">
          <span className="text-xs text-muted">Add to group (optional)</span>
          <input id="connect-group" list="group-list" value={group} onChange={(e) => setGroup(e.target.value)} className="rounded border border-line bg-paper px-3 py-2" placeholder="Finance EN" />
          <datalist id="group-list">
            {groups.map((g) => (
              <option key={g} value={g} />
            ))}
          </datalist>
        </label>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {(apps.data ?? []).map((p) => (
            <div key={p.platform} className="flex flex-col gap-2 rounded border border-line p-3">
              <span className="flex items-center gap-2 font-semibold">
                <PlatformBadge platform={p.platform} /> {p.label}
              </span>
              {p.configured ? (
                <Button size="sm" variant="primary" onClick={() => go(p.platform)}>
                  Sign in with {p.label}
                </Button>
              ) : (
                <Link href="/settings#platform-apps" className="text-xs text-paid underline">
                  Add your {p.label} app keys first
                </Link>
              )}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

function PracticePanel({ groups, onClose, onCreated }: { groups: string[]; onClose: () => void; onCreated: () => void }) {
  const { notify } = useStore();
  const tzGuess = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC";
  const [f, setF] = useState({ platform: "instagram" as PlatformId, handle: "", group_name: "", timezone: tzGuess || "UTC", daily_cap: 3, posting_start: "09:00", posting_end: "21:00" });
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    setErr(null);
    try {
      await api.createAccount(f);
      notify(`Added practice account ${f.handle}`);
      onCreated();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <Card title="Add a practice account" actions={<button aria-label="Close" onClick={onClose} className="rounded p-1 hover:bg-paper"><X size={16} /></button>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">Practice accounts go through scheduling, approval and publishing exactly like real ones, but nothing is posted. Use them to try the flow before connecting real accounts.</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label htmlFor="pa-platform" className="flex flex-col gap-1">
            <span className="text-xs text-muted">Platform</span>
            <select id="pa-platform" value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value as PlatformId })} className="rounded border border-line bg-surface px-2 py-2">
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_RULES[p].label}
                </option>
              ))}
            </select>
          </label>
          <Field id="pa-handle" label="Handle" value={f.handle} onChange={(v) => setF({ ...f, handle: v })} placeholder="@moneywithmaya" />
          <Field id="pa-group" label="Group" value={f.group_name} onChange={(v) => setF({ ...f, group_name: v })} placeholder={groups[0] ?? "Finance EN"} />
          <Field id="pa-tz" label="Time zone" value={f.timezone} onChange={(v) => setF({ ...f, timezone: v })} placeholder="Europe/London" />
          <Field id="pa-start" label="Posting from (HH:MM)" value={f.posting_start} onChange={(v) => setF({ ...f, posting_start: v })} />
          <Field id="pa-end" label="Posting until (HH:MM)" value={f.posting_end} onChange={(v) => setF({ ...f, posting_end: v })} />
          <label htmlFor="pa-cap" className="flex flex-col gap-1">
            <span className="text-xs text-muted">Posts per day, at most</span>
            <input id="pa-cap" type="number" min={1} max={500} value={f.daily_cap} onChange={(e) => setF({ ...f, daily_cap: Math.max(1, Number(e.target.value) || 1) })} className="rounded border border-line bg-paper px-3 py-2" />
          </label>
        </div>
        {err && <p className="text-rec">{err}</p>}
        <Button variant="primary" className="self-start" disabled={!f.handle.trim()} onClick={save}>
          Add practice account
        </Button>
      </div>
    </Card>
  );
}

function Field({ id, label, value, onChange, placeholder }: { id: string; label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <input id={id} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className="rounded border border-line bg-paper px-3 py-2" />
    </label>
  );
}
