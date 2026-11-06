"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ChevronLeft } from "lucide-react";
import { api, type ApiAccount } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";
import { LivePostsTable } from "./LivePostsTable";
import { Badge, Button, Card, PageHeader, PlatformBadge, Stat, Toggle } from "./ui";

export function LiveAccount({ id }: { id: string }) {
  const router = useRouter();
  const { notify } = useStore();
  const accounts = usePoll(api.accounts, { intervalMs: 15000 });
  const stats = usePoll(api.accountStats, { intervalMs: 15000 });
  const a = accounts.data?.find((x) => x.id === id);
  const st = stats.data?.[id];
  const [f, setF] = useState<Partial<ApiAccount> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (a && !f) setF({ group_name: a.group_name, timezone: a.timezone, daily_cap: a.daily_cap, posting_start: a.posting_start, posting_end: a.posting_end, language: a.language });
  }, [a, f]);

  if (accounts.error && !a) return <p className="text-sm text-rec">{accounts.error}</p>;
  if (!accounts.data) return <p className="text-sm text-muted">Loading…</p>;
  if (!a) {
    return (
      <>
        <PageHeader title="Account not found" />
        <Link href="/accounts" className="text-accent">
          Back to accounts
        </Link>
      </>
    );
  }

  async function save(body: Parameters<typeof api.updateAccount>[1], ok: string) {
    setErr(null);
    try {
      await api.updateAccount(id, body);
      notify(ok);
      accounts.refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const dirty = f && (Object.keys(f) as (keyof ApiAccount)[]).some((k) => f[k] !== a[k]);

  return (
    <>
      <Link href="/accounts" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ChevronLeft size={16} /> Accounts
      </Link>
      <PageHeader
        eyebrow={a.connection === "simulated" ? "Practice account" : "Connected through platform login"}
        title={a.handle}
        description={`${a.language} · ${a.timezone} · up to ${a.daily_cap} posts a day, ${a.posting_start}–${a.posting_end}`}
        actions={
          <label className="flex items-center gap-2 text-sm">
            <Toggle
              on={a.status === "connected"}
              label={`Posting on ${a.handle}`}
              onChange={() => save({ status: a.status === "paused" ? "connected" : "paused" }, a.status === "paused" ? "Posting resumed" : "Posting paused")}
            />
            {a.status === "paused" ? "Posting paused" : a.status === "reconnect" ? "Needs reconnect" : "Posting on"}
          </label>
        }
      />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <PlatformBadge platform={a.platform} full />
        {a.group_name && <Badge tone="accent">{a.group_name}</Badge>}
        {a.token_expires_at && <span className="text-xs text-muted">Login valid until {new Date(a.token_expires_at).toLocaleDateString()}</span>}
      </div>
      {a.last_error && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {a.last_error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Published, all time" value={String(st?.published ?? 0)} />
        <Stat label="Published, last 24 h" value={`${st?.posted_24h ?? 0} / ${a.daily_cap}`} />
        <Stat label="Waiting" value={String(st?.waiting ?? 0)} />
        <Stat label="Failed or unconfirmed" value={String(st?.problems ?? 0)} />
      </div>
      <p className="-mt-3 text-xs text-muted">Views, watch time and followers arrive with the Measure phase.</p>

      <Card title="Account settings">
        {f && (
          <div className="flex flex-col gap-3 text-sm">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <In id="ac-group" label="Group" value={f.group_name ?? ""} onChange={(v) => setF({ ...f, group_name: v })} />
              <In id="ac-tz" label="Time zone" value={f.timezone ?? ""} onChange={(v) => setF({ ...f, timezone: v })} />
              <In id="ac-lang" label="Language" value={f.language ?? ""} onChange={(v) => setF({ ...f, language: v })} />
              <In id="ac-start" label="Posting from (HH:MM)" value={f.posting_start ?? ""} onChange={(v) => setF({ ...f, posting_start: v })} />
              <In id="ac-end" label="Posting until (HH:MM)" value={f.posting_end ?? ""} onChange={(v) => setF({ ...f, posting_end: v })} />
              <label htmlFor="ac-cap" className="flex flex-col gap-1">
                <span className="text-xs text-muted">Posts per day, at most</span>
                <input id="ac-cap" type="number" min={1} max={500} value={f.daily_cap ?? 1} onChange={(e) => setF({ ...f, daily_cap: Math.max(1, Number(e.target.value) || 1) })} className="rounded border border-line bg-paper px-3 py-2" />
              </label>
            </div>
            {err && <p className="text-rec">{err}</p>}
            <Button variant="primary" className="self-start" disabled={!dirty} onClick={() => save(f, "Account saved")}>
              Save
            </Button>
          </div>
        )}
      </Card>

      {(a.platform === "pinterest" || a.platform === "youtube" || a.connection === "simulated") && (
        <Card title="Platform options">
          <div className="flex flex-col gap-3 text-sm">
            {a.platform === "pinterest" && (
              <label htmlFor="ac-board" className="flex max-w-sm flex-col gap-1">
                <span className="text-xs text-muted">Board to pin to</span>
                <select id="ac-board" value={a.options.board_id ?? ""} onChange={(e) => save({ options: { board_id: e.target.value } }, "Board saved")} className="rounded border border-line bg-surface px-2 py-2">
                  {!(a.options.boards ?? []).length && <option value="">No boards found: create one on Pinterest, then reconnect</option>}
                  {(a.options.boards ?? []).map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {a.platform === "youtube" && (
              <label htmlFor="ac-privacy" className="flex max-w-sm flex-col gap-1">
                <span className="text-xs text-muted">Visibility of new Shorts</span>
                <select id="ac-privacy" value={a.options.privacy ?? "public"} onChange={(e) => save({ options: { privacy: e.target.value } }, "Saved")} className="rounded border border-line bg-surface px-2 py-2">
                  <option value="public">Public</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="private">Private</option>
                </select>
              </label>
            )}
            {a.connection === "simulated" && (
              <label htmlFor="ac-sim" className="flex max-w-sm flex-col gap-1">
                <span className="text-xs text-muted">Practice behaviour (to see how failures are handled)</span>
                <select id="ac-sim" value={a.options.simulate ?? "ok"} onChange={(e) => save({ options: { simulate: e.target.value } }, "Saved")} className="rounded border border-line bg-surface px-2 py-2">
                  <option value="ok">Always succeeds</option>
                  <option value="fail_once">Fails once, then succeeds (retry)</option>
                  <option value="timeout">Platform doesn&apos;t answer (verify, no double post)</option>
                  <option value="expired">Login expired (reconnect)</option>
                  <option value="fail">Always fails</option>
                </select>
              </label>
            )}
          </div>
        </Card>
      )}

      <Card title="Posts from this account" padded={false}>
        <LivePostsTable filter={{ account_id: id }} showAccount={false} />
      </Card>

      <div>
        {confirmDelete ? (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            Remove {a.handle} and all its scheduled posts?
            <Button
              variant="danger"
              size="sm"
              onClick={async () => {
                try {
                  await api.deleteAccount(id);
                  notify(`Removed ${a.handle}`);
                  router.push("/accounts");
                } catch (e) {
                  notify(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              Remove for good
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
              Keep
            </Button>
          </span>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
            Remove account
          </Button>
        )}
      </div>
    </>
  );
}

function In({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)} className="rounded border border-line bg-paper px-3 py-2" />
    </label>
  );
}
