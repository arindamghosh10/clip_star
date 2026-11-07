"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Copy, Download } from "lucide-react";
import { useAuth } from "./Auth";
import { FormError, Input, errText } from "./Form";
import { Badge, Button, Card, EmptyNote, Toggle, cx } from "./ui";
import { NOTIFY_KINDS, api, backupUrl, fmtBytes, fmtTime, type ApiUser, type Role, type StoragePolicy } from "@/lib/api";
import { currentSubscription, disablePush, enablePush, pushSupport } from "@/lib/push";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const ROLES: Role[] = ["owner", "editor", "reviewer", "viewer"];
const ROLE_LABEL: Record<Role, string> = { owner: "Owner", editor: "Editor", reviewer: "Reviewer", viewer: "Viewer" };

export function ProfileCard() {
  const { state, refresh } = useAuth();
  const { notify } = useStore();
  const user = state?.user;
  const [name, setName] = useState(user?.name ?? "");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [error, setError] = useState<string | null>(null);
  if (!user) return null;

  async function saveName(e: FormEvent) {
    e.preventDefault();
    try {
      await api.updateMe({ name });
      await refresh();
      notify("Name saved");
    } catch (err) {
      setError(errText(err));
    }
  }
  async function savePw(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.updateMe({ current_password: pw.current, new_password: pw.next });
      setPw({ current: "", next: "" });
      notify("Password changed. Other devices were signed out.");
    } catch (err) {
      setError(errText(err));
    }
  }
  return (
    <Card title="Your account">
      <div className="flex flex-col gap-4 text-sm">
        <p className="text-muted">
          {user.email} · {ROLE_LABEL[user.role]}
        </p>
        <form onSubmit={saveName} className="flex items-end gap-2">
          <div className="flex-1">
            <Input id="me-name" label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <Button type="submit" disabled={!name.trim() || name === user.name}>Save</Button>
        </form>
        <form onSubmit={savePw} className="grid gap-2 sm:grid-cols-2">
          <Input id="pw-cur" label="Current password" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required />
          <Input id="pw-new" label="New password" type="password" autoComplete="new-password" minLength={10} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required />
          <Button type="submit" className="sm:col-span-2" disabled={!pw.current || pw.next.length < 10}>Change password</Button>
        </form>
        <FormError error={error} />
      </div>
    </Card>
  );
}

export function NotificationsCard() {
  const { state, refresh } = useAuth();
  const { notify } = useStore();
  const user = state?.user;
  if (!user) return null;
  async function save(body: { email_notifications?: boolean; kinds?: string[] }) {
    try {
      await api.updateMe(body);
      await refresh();
      notify("Notification settings saved");
    } catch (e) {
      notify(errText(e));
    }
  }
  const kinds = user.prefs.kinds;
  return (
    <Card title={<span id="notifications">Notifications</span>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">Everything shows under the bell. Choose what is also emailed to {user.email}.</p>
        {!state?.email_enabled && <p className="rounded bg-paid-soft px-3 py-2 text-xs text-paid">Email isn&apos;t set up on this server, so nothing is emailed yet. The person running clip_star can add CLIPSTAR_SMTP_HOST and related settings.</p>}
        <label className="flex items-center justify-between gap-3">
          <span>Email me</span>
          <Toggle on={user.prefs.email} onChange={() => save({ email_notifications: !user.prefs.email })} label="Email notifications" />
        </label>
        <div className={cx("grid gap-1.5 sm:grid-cols-2", !user.prefs.email && "opacity-50")}>
          {Object.entries(NOTIFY_KINDS).map(([k, label]) => (
            <label key={k} className="flex items-center gap-2">
              <input type="checkbox" checked={kinds.includes(k)} disabled={!user.prefs.email} onChange={() => save({ kinds: kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k] })} />
              {label}
            </label>
          ))}
        </div>
        <PushSection />
      </div>
    </Card>
  );
}

function PushSection() {
  const { notify } = useStore();
  const st = usePoll(api.pushStatus, { intervalMs: 60000 });
  const [here, setHere] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const support = typeof window === "undefined" ? "unsupported" : pushSupport();
  useEffect(() => {
    currentSubscription().then((s) => setHere(!!s)).catch(() => setHere(false));
  }, []);
  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      notify(ok);
      st.refresh();
      setHere(!!(await currentSubscription()));
    } catch (e) {
      notify(errText(e));
    } finally {
      setBusy(false);
    }
  }
  const kinds = st.data?.kinds ?? [];
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <span className="flex items-center justify-between gap-3">
        <span>
          <span className="font-medium">Push to this device</span>
          <span className="block text-xs text-muted">
            {support === "ios-install"
              ? "On iPhone/iPad: tap Share → Add to Home Screen, open clip_star from there, then turn this on."
              : support === "denied"
                ? "Notifications are blocked for this site in your browser settings."
                : support === "unsupported"
                  ? "This browser doesn't support push notifications."
                  : `${st.data?.devices ?? 0} device${st.data?.devices === 1 ? "" : "s"} set up for you.`}
          </span>
        </span>
        {support === "ok" &&
          (here ? (
            <Button size="sm" disabled={busy} onClick={() => run(disablePush, "Push turned off on this device")}>Turn off here</Button>
          ) : (
            <Button size="sm" variant="primary" disabled={busy || here === null} onClick={() => run(enablePush, "Push is on for this device")}>Turn on here</Button>
          ))}
      </span>
      {(st.data?.devices ?? 0) > 0 && (
        <>
          <label className="flex items-center justify-between gap-3">
            <span>Send me push notifications in this workspace</span>
            <Toggle on={!!st.data?.push} onChange={() => run(() => api.pushPrefs({ push: !st.data?.push }), "Saved")} label="Push in this workspace" />
          </label>
          <div className={cx("grid gap-1.5 sm:grid-cols-2", !st.data?.push && "opacity-50")}>
            {Object.entries(NOTIFY_KINDS).map(([k, label]) => (
              <label key={k} className="flex items-center gap-2">
                <input type="checkbox" checked={kinds.includes(k)} disabled={!st.data?.push} onChange={() => run(() => api.pushPrefs({ kinds: kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k] }), "Saved")} />
                {label}
              </label>
            ))}
          </div>
          <Button size="sm" className="self-start" disabled={busy} onClick={() => run(async () => { const r = await api.pushTest(); if (!r.sent) throw new Error("No device accepted the test. Turn push off and on again here."); }, "Test sent")}>Send a test</Button>
        </>
      )}
    </div>
  );
}

export function TeamCard() {
  const { state, can } = useAuth();
  const { notify } = useStore();
  const users = usePoll(api.users, { intervalMs: 60000 });
  const [f, setF] = useState<{ email: string; name: string; role: Role }>({ email: "", name: "", role: "editor" });
  const [link, setLink] = useState<{ email: string; url: string; emailed: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const owner = can("owner") && !!state?.user;
  const me = state?.user?.id;

  async function invite(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api.inviteUser(f.email, f.name, f.role);
      if (r.invite_url) setLink({ email: r.email, url: r.invite_url, emailed: r.emailed });
      else notify(`${r.email} already has a login here and was added to this workspace${r.emailed ? " (emailed)" : ""}.`);
      setF({ email: "", name: "", role: "editor" });
      users.refresh();
    } catch (err) {
      setError(errText(err));
    }
  }
  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      notify(ok);
      users.refresh();
    } catch (e) {
      notify(errText(e));
    }
  }
  async function reinvite(u: ApiUser) {
    try {
      const r = await api.reinvite(u.id);
      if (r.invite_url) setLink({ email: r.email, url: r.invite_url, emailed: r.emailed });
    } catch (e) {
      notify(errText(e));
    }
  }

  return (
    <Card title="Team" className="lg:col-span-2" padded={false}>
      <div className="flex flex-col gap-4 p-5 text-sm">
        <p className="text-muted">
          {Object.entries(state?.roles ?? {}).map(([r, h]) => (
            <span key={r} className="mr-3 inline-block">
              <b className="text-ink">{ROLE_LABEL[r as Role]}</b>: {h}
            </span>
          ))}
        </p>
        {owner && (
          <form onSubmit={invite} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end">
            <Input id="inv-email" label="Email" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
            <Input id="inv-name" label="Name (optional)" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
            <label className="flex flex-col gap-1">
              <span className="text-muted">Role</span>
              <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })} className="rounded border border-line bg-paper px-3 py-2">
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </label>
            <Button variant="primary" type="submit">Invite</Button>
          </form>
        )}
        <FormError error={error} />
        {link && (
          <div className="flex flex-col gap-1.5 rounded border border-accent/30 bg-accent-soft p-3">
            <span>
              {link.emailed ? `Invite emailed to ${link.email}. You can also send this link:` : `Send this link to ${link.email} (it works for 7 days, once):`}
            </span>
            <span className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded bg-surface px-2 py-1 font-mono text-xs">{link.url}</code>
              <Button size="sm" onClick={() => navigator.clipboard?.writeText(link.url).then(() => notify("Link copied"))}>
                <Copy size={12} /> Copy
              </Button>
            </span>
          </div>
        )}
      </div>
      <ul className="border-t border-line">
        {users.data?.map((u) => (
          <li key={u.id} className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3 text-sm last:border-0">
            <span className="min-w-0 flex-1">
              <span className="font-medium">{u.name || u.email}</span>
              {u.id === me && <span className="text-muted"> (you)</span>}
              <span className="block text-xs text-muted">
                {u.email} · {u.pending_invite ? "invite not accepted yet" : u.last_login_at ? `last sign-in ${fmtTime(u.last_login_at)}` : "never signed in"}
              </span>
            </span>
            {u.disabled && <Badge tone="rec">disabled</Badge>}
            {owner ? (
              <span className="flex flex-wrap items-center gap-1.5">
                <select aria-label={`Role for ${u.email}`} value={u.role} onChange={(e) => act(() => api.updateUser(u.id, { role: e.target.value as Role }), "Role changed")} className="rounded border border-line bg-paper px-2 py-1 text-xs">
                  {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                </select>
                {u.pending_invite && <Button size="sm" onClick={() => reinvite(u)}>New link</Button>}
                {u.id !== me && (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => act(() => api.updateUser(u.id, { disabled: !u.disabled }), u.disabled ? "Access restored" : "Access paused; they were signed out")}>
                      {u.disabled ? "Enable" : "Disable"}
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => confirm(`Remove ${u.email} from the team?`) && act(() => api.removeUser(u.id), "Removed")}>
                      Remove
                    </Button>
                  </>
                )}
              </span>
            ) : (
              <Badge>{ROLE_LABEL[u.role]}</Badge>
            )}
          </li>
        ))}
        {users.data && !users.data.length && (
          <li className="p-5">
            <EmptyNote>No team yet.</EmptyNote>
          </li>
        )}
      </ul>
    </Card>
  );
}

const KIND_LABEL: Record<string, string> = { originals: "Original videos", previews: "Previews", clips: "Clips", audio: "Audio extracts", analysis: "Transcripts & analysis", backups: "Backups", other: "Other" };

export function WorkspaceCard() {
  const { state, can, refresh } = useAuth();
  const { notify } = useStore();
  const [name, setName] = useState(state?.workspace?.name ?? "");
  const [confirmName, setConfirmName] = useState("");
  const [deleting, setDeleting] = useState(false);
  const ws = state?.workspace;
  if (!ws) return null;
  const owner = can("owner");
  const only = (state?.workspaces.length ?? 1) <= 1;
  async function rename() {
    try {
      await api.updateWorkspace({ name });
      await refresh();
      notify("Workspace renamed");
    } catch (e) {
      notify(errText(e));
    }
  }
  async function remove() {
    try {
      await api.deleteWorkspace(ws!.id, confirmName);
      window.location.href = "/";
    } catch (e) {
      notify(errText(e));
    }
  }
  return (
    <Card title="This workspace">
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">Each workspace has its own videos, clips, accounts, team, platform apps, settings and stats. Use one per creator or brand. Switch between them from the menu at the bottom of the sidebar.</p>
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Input id="ws-name" label="Name" value={name} disabled={!owner} onChange={(e) => setName(e.target.value)} />
          </div>
          {owner && <Button disabled={!name.trim() || name === ws.name} onClick={rename}>Rename</Button>}
        </div>
        {owner && !only && (
          <div className="flex flex-col gap-2 border-t border-line pt-3">
            {!deleting ? (
              <Button variant="danger" className="self-start" onClick={() => setDeleting(true)}>Delete this workspace…</Button>
            ) : (
              <>
                <p className="text-rec">This deletes every video, clip, account connection, post record and setting in “{ws.name}”, including the files. It can&apos;t be undone. Posts already on social platforms stay there.</p>
                <Input id="ws-confirm" label={`Type ${ws.name} to confirm`} value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
                <span className="flex gap-2">
                  <Button variant="danger" disabled={confirmName !== ws.name} onClick={remove}>Delete forever</Button>
                  <Button variant="ghost" onClick={() => { setDeleting(false); setConfirmName(""); }}>Keep it</Button>
                </span>
              </>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}

export function StorageCard() {
  const { can, state } = useAuth();
  const { notify } = useStore();
  const u = usePoll(api.storage, { intervalMs: 60000 });
  const [p, setP] = useState<StoragePolicy | null>(null);
  useEffect(() => {
    if (u.data && !p) setP(u.data.policy);
  }, [u.data, p]);
  const owner = can("owner");
  const admin = !state?.user || !!state.user.is_admin;
  const dirty = p && u.data && JSON.stringify(p) !== JSON.stringify(u.data.policy);
  const max = Math.max(1, ...Object.values(u.data?.by_kind ?? {}));
  async function save() {
    if (!p) return;
    try {
      const r = await api.setStorage(p);
      setP(r.policy);
      u.refresh();
      notify("Storage rules saved. They apply at the next daily clean-up.");
    } catch (e) {
      notify(errText(e));
    }
  }
  return (
    <Card title="Storage" actions={u.data && <span className="text-xs text-muted">{fmtBytes(u.data.free_bytes)} free on disk</span>}>
      <div className="flex flex-col gap-4 text-sm">
        {u.data && u.data.free_bytes / 1024 ** 3 < u.data.low_disk_gb && <p className="rounded bg-rec/10 px-3 py-2 text-xs text-rec">Disk space is low. Processing may fail until space is freed.</p>}
        <ul className="flex flex-col gap-1.5">
          {Object.entries(u.data?.by_kind ?? {})
            .filter(([, v]) => v > 0)
            .sort((a, b) => b[1] - a[1])
            .map(([k, v]) => (
              <li key={k} className="flex items-center gap-3">
                <span className="w-40 shrink-0 truncate">{KIND_LABEL[k] ?? k}</span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-line" aria-hidden>
                  <span className="block h-full rounded-full bg-accent" style={{ width: `${(v / max) * 100}%` }} />
                </span>
                <span className="tnum w-20 shrink-0 text-right font-mono text-xs">{fmtBytes(v)}</span>
              </li>
            ))}
        </ul>
        {p && (
          <fieldset disabled={!owner} className="flex flex-col gap-3 border-t border-line pt-3">
            <label className="flex items-center justify-between gap-3">
              <span>Delete audio extracts once a video is ready</span>
              <Toggle on={p.delete_audio} onChange={() => setP({ ...p, delete_audio: !p.delete_audio })} label="Delete audio extracts" />
            </label>
            <label className="flex items-center justify-between gap-3">
              <span>Delete renders of rejected clips after (days)</span>
              <input type="number" min={0} max={3650} value={p.rejected_render_days ?? ""} placeholder="never" onChange={(e) => setP({ ...p, rejected_render_days: e.target.value === "" ? null : Number(e.target.value) })} className="tnum w-24 rounded border border-line bg-paper px-2 py-1" />
            </label>
            <label className="flex items-center justify-between gap-3">
              <span>
                Archive videos older than (days)
                <span className="block text-xs text-muted">Deletes the original and preview once nothing is waiting to post. Clips, transcripts and stats stay, but the video can&apos;t be re-cut.</span>
              </span>
              <input type="number" min={1} max={3650} value={p.archive_after_days ?? ""} placeholder="off" onChange={(e) => setP({ ...p, archive_after_days: e.target.value === "" ? null : Number(e.target.value) })} className="tnum w-24 shrink-0 rounded border border-line bg-paper px-2 py-1" />
            </label>
            {owner && (
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" disabled={!dirty} onClick={save}>Save rules</Button>
                {admin && <Button onClick={() => api.cleanStorage().then(() => notify("Clean-up started. See Activity.")).catch((e) => notify(errText(e)))}>Clean up now</Button>}
              </div>
            )}
          </fieldset>
        )}
      </div>
    </Card>
  );
}

export function BackupsCard() {
  const { state } = useAuth();
  const { notify } = useStore();
  const admin = !state?.user || !!state.user.is_admin;
  const b = usePoll(() => (admin ? api.backups() : Promise.resolve(null)), { intervalMs: 30000, deps: [admin] });
  if (!admin) return null; // server-wide: only the person who runs this server
  async function now(media: boolean) {
    try {
      await api.backupNow(media);
      notify("Backup started. It appears here when done.");
    } catch (e) {
      notify(errText(e));
    }
  }
  return (
    <Card title="Backups" actions={<span className="flex gap-2"><Button size="sm" onClick={() => now(false)}>Back up now</Button><Button size="sm" variant="ghost" onClick={() => now(true)}>With videos</Button></span>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">
          {b.data?.scheduled ? `A backup of the database and encryption key runs daily; the newest ${b.data.keep} are kept in ${b.data.folder}.` : "Scheduled backups are off (set CLIPSTAR_BACKUP_DIR). You can still back up now."}{" "}
          Backups contain the key that unlocks your platform logins: download them to somewhere private and off this machine.
        </p>
        {b.error && <p className="text-xs text-rec">{b.error}</p>}
        <ul className="flex flex-col">
          {b.data?.items.map((it) => (
            <li key={it.name} className="flex items-center justify-between gap-2 border-b border-line py-2 last:border-0">
              <span className="min-w-0">
                <span className="block truncate font-mono text-xs">{it.name}</span>
                <span className="text-xs text-muted">{fmtTime(it.created_at)} · {fmtBytes(it.size_bytes)}{it.media ? " · with videos" : ""}</span>
              </span>
              <a href={backupUrl(it.name)} className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent" download>
                <Download size={12} /> Download
              </a>
            </li>
          ))}
          {b.data && !b.data.items.length && <EmptyNote>No backups yet.</EmptyNote>}
        </ul>
        <p className="text-xs text-muted">To restore: stop clip_star, run <code className="font-mono">python -m clipstar.backup restore FILE --yes</code>, then start it again. See docs/OPERATIONS.md.</p>
      </div>
    </Card>
  );
}

export function BudgetCard() {
  const { can } = useAuth();
  const { notify } = useStore();
  const b = usePoll(api.budget, { intervalMs: 60000 });
  const [limit, setLimit] = useState<string>("");
  const [warn, setWarn] = useState(80);
  useEffect(() => {
    if (b.data) {
      setLimit(b.data.limit_usd == null ? "" : String(b.data.limit_usd));
      setWarn(b.data.warn_pct);
    }
  }, [b.data?.limit_usd, b.data?.warn_pct]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = b.data;
  const pct = d && d.limit_usd ? Math.min(100, (d.spent_usd / Math.max(d.limit_usd, 1e-9)) * 100) : 0;
  async function save() {
    try {
      await api.setBudget(limit === "" ? null : Number(limit), warn);
      b.refresh();
      notify("Budget saved");
    } catch (e) {
      notify(errText(e));
    }
  }
  return (
    <Card title="Spending on paid engines · this month">
      {!d ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : (
        <div className="flex flex-col gap-3 text-sm">
          <div className="flex items-baseline gap-2">
            <span className="tnum text-2xl font-bold">${d.spent_usd.toFixed(2)}</span>
            <span className="text-muted">{d.limit_usd != null ? `of $${d.limit_usd.toFixed(2)}` : "no limit set"}</span>
            {d.blocked && <Badge tone="rec">limit reached · free engines in use</Badge>}
          </div>
          {d.limit_usd != null && (
            <div className="h-2 overflow-hidden rounded-full bg-line" role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label="Budget used">
              <div className={cx("h-full rounded-full", pct >= 100 ? "bg-rec" : pct >= d.warn_pct ? "bg-gate" : "bg-accent")} style={{ width: `${pct}%` }} />
            </div>
          )}
          {d.by_engine.length > 0 && (
            <ul className="flex flex-col gap-1 text-xs">
              {d.by_engine.map((r) => (
                <li key={r.engine + r.stage} className="flex justify-between gap-2">
                  <span>{r.engine} · {r.stage} · {r.calls} call{r.calls === 1 ? "" : "s"}</span>
                  <span className="tnum font-mono">${r.cost_usd.toFixed(3)}</span>
                </li>
              ))}
            </ul>
          )}
          {can("owner") && (
            <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
              <Input id="budget" label="Monthly limit (USD, empty = none)" type="number" min={0} step="0.5" value={limit} onChange={(e) => setLimit(e.target.value)} />
              <Input id="warn" label="Warn at (%)" type="number" min={10} max={99} value={warn} onChange={(e) => setWarn(Number(e.target.value) || 80)} />
              <Button variant="primary" onClick={save}>Save</Button>
            </div>
          )}
          <p className="text-xs text-muted">When the limit is reached, paid engines stop and the free engine does the work, with a note on the video. {d.note}</p>
        </div>
      )}
    </Card>
  );
}
