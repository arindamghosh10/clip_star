"use client";

import { useState, type FormEvent } from "react";
import { Copy, ExternalLink, KeyRound, Webhook as WebhookIcon } from "lucide-react";
import { useAuth } from "./Auth";
import { FormError, Input, errText } from "./Form";
import { Badge, Button, Card, EmptyNote, Toggle, cx } from "./ui";
import { api, apiDocsUrl, fmtTime, type ApiDelivery, type ApiWebhook, type Role } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, editor: 2, owner: 3 };
const ROLE_LABEL: Record<Role, string> = { owner: "Owner", editor: "Editor", reviewer: "Reviewer", viewer: "Viewer (read only)" };

function Secret({ label, value, onDone }: { label: string; value: string; onDone: () => void }) {
  const { notify } = useStore();
  return (
    <div className="flex flex-col gap-1.5 rounded border border-gate/40 bg-gate-soft p-3 text-sm">
      <span className="font-medium">{label}</span>
      <span className="flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded bg-surface px-2 py-1 font-mono text-xs">{value}</code>
        <Button size="sm" onClick={() => navigator.clipboard?.writeText(value).then(() => notify("Copied"))}>
          <Copy size={12} /> Copy
        </Button>
      </span>
      <span className="text-xs text-muted">It won&apos;t be shown again. Store it somewhere safe.</span>
      <Button size="sm" variant="ghost" className="self-start" onClick={onDone}>I&apos;ve saved it</Button>
    </div>
  );
}

export function ApiKeysCard() {
  const { state } = useAuth();
  const { notify } = useStore();
  const keys = usePoll(api.keys, { intervalMs: 60000 });
  const [f, setF] = useState<{ name: string; role: Role }>({ name: "", role: "viewer" });
  const [shown, setShown] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const me = state?.user;
  if (!me) return null;
  const roles = (Object.keys(RANK) as Role[]).filter((r) => RANK[r] <= RANK[me.role]).reverse();

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const k = await api.createKey(f.name, f.role);
      setShown(k.key);
      setF({ name: "", role: "viewer" });
      keys.refresh();
    } catch (err) {
      setError(errText(err));
    }
  }
  return (
    <Card title={<span className="flex items-center gap-2"><KeyRound size={16} /> API keys</span>} actions={<a href={apiDocsUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-accent">API reference <ExternalLink size={12} /></a>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">For your own scripts, automation tools and AI assistants (the clip_star MCP server). A key acts as you, with the access you choose, never more than yours.</p>
        <form onSubmit={create} className="flex flex-col gap-2">
          <Input id="key-name" label="Name" placeholder="e.g. Claude assistant" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-muted">Access</span>
              <select id="key-role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })} className="rounded border border-line bg-paper px-3 py-2">
                {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </label>
            <Button variant="primary" type="submit">Create key</Button>
          </div>
        </form>
        <FormError error={error} />
        {shown && <Secret label="Your new API key" value={shown} onDone={() => setShown(null)} />}
        <ul className="flex flex-col">
          {keys.data?.map((k) => (
            <li key={k.id} className="flex items-center justify-between gap-2 border-b border-line py-2 last:border-0">
              <span className="min-w-0">
                <span className="font-medium">{k.name}</span> <Badge>{ROLE_LABEL[k.role].split(" ")[0]}</Badge>
                <span className="block font-mono text-xs text-muted">
                  {k.prefix}… · {k.last_used_at ? `used ${fmtTime(k.last_used_at)}` : "never used"}
                  {k.user_id !== me.id && k.user_email ? ` · ${k.user_email}` : ""}
                </span>
              </span>
              <Button size="sm" variant="danger" onClick={() => confirm(`Revoke "${k.name}"? Anything using it stops working.`) && api.revokeKey(k.id).then(() => { notify("Key revoked"); keys.refresh(); }).catch((e) => notify(errText(e)))}>
                Revoke
              </Button>
            </li>
          ))}
          {keys.data && !keys.data.length && <EmptyNote>No API keys yet.</EmptyNote>}
        </ul>
      </div>
    </Card>
  );
}

function Deliveries({ hook }: { hook: ApiWebhook }) {
  const { notify } = useStore();
  const d = usePoll(() => api.deliveries(hook.id), { intervalMs: 5000, deps: [hook.id] });
  const tone = (x: ApiDelivery) => (x.status === "sent" ? "free" : x.status === "failed" ? "rec" : "gate");
  return (
    <ul className="flex flex-col gap-1 border-t border-line pt-2">
      {!d.data?.length && <li className="text-xs text-muted">No deliveries yet. Send a test.</li>}
      {d.data?.slice(0, 8).map((x) => (
        <li key={x.id} className="flex items-center justify-between gap-2 text-xs">
          <span className="min-w-0">
            <Badge tone={tone(x)}>{x.status}</Badge> <span className="font-mono">{x.event_type}</span>
            <span className="text-muted"> · {x.created_at ? fmtTime(x.created_at) : ""}{x.response_code ? ` · HTTP ${x.response_code}` : ""}{x.attempts > 1 ? ` · ${x.attempts} tries` : ""}</span>
            {x.error && x.status !== "sent" && <span className="block truncate text-rec" title={x.error}>{x.error}</span>}
          </span>
          {x.status === "failed" && (
            <Button size="sm" variant="ghost" onClick={() => api.redeliver(hook.id, x.id).then(() => { notify("Sending again"); d.refresh(); }).catch((e) => notify(errText(e)))}>
              Resend
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

export function WebhooksCard() {
  const { can } = useAuth();
  const { notify } = useStore();
  const hooks = usePoll(api.webhooks, { intervalMs: 15000 });
  const types = usePoll(api.eventTypes, { intervalMs: 600000 });
  const [f, setF] = useState<{ url: string; description: string; events: string[] }>({ url: "", description: "", events: ["*"] });
  const [secret, setSecret] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!can("owner")) return null;
  const all = f.events.includes("*");

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const h = await api.createWebhook(f.url, f.events, f.description);
      setSecret(h.secret);
      setOpen(h.id);
      setF({ url: "", description: "", events: ["*"] });
      hooks.refresh();
    } catch (err) {
      setError(errText(err));
    }
  }
  const toggle = (t: string) => setF({ ...f, events: all ? [t] : f.events.includes(t) ? f.events.filter((x) => x !== t) : [...f.events, t] });
  const act = (p: Promise<unknown>, ok: string) => p.then(() => { notify(ok); hooks.refresh(); }).catch((e) => notify(errText(e)));

  return (
    <Card title={<span className="flex items-center gap-2"><WebhookIcon size={16} /> Webhooks</span>} className="lg:col-span-2">
      <div className="flex flex-col gap-4 text-sm">
        <p className="text-muted">
          clip_star sends a signed POST to your address when something happens: a video is ready, a post goes live, a comment arrives. Use it with n8n, Zapier, Make, Slack or your own code. Failed deliveries are retried; after 20 failures in a row the webhook is switched off. How to check the signature: docs/API.md.
        </p>
        <form onSubmit={create} className="flex flex-col gap-2">
          <div className="grid gap-2 sm:grid-cols-[2fr_1fr]">
            <Input id="wh-url" label="Address (https://…)" type="url" required value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
            <Input id="wh-desc" label="Note (optional)" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
          </div>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-muted">Events</legend>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={all} onChange={() => setF({ ...f, events: all ? [] : ["*"] })} /> Everything
            </label>
            <div className="grid gap-1 sm:grid-cols-2">
              {Object.entries(types.data ?? {}).map(([t, label]) => (
                <label key={t} className={cx("flex items-start gap-2", all && "opacity-50")}>
                  <input type="checkbox" className="mt-1" checked={all || f.events.includes(t)} disabled={all} onChange={() => toggle(t)} />
                  <span>
                    <span className="font-mono text-xs">{t}</span>
                    <span className="block text-xs text-muted">{label}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <Button variant="primary" type="submit" className="self-start" disabled={!f.url || !f.events.length}>Add webhook</Button>
        </form>
        <FormError error={error} />
        {secret && <Secret label="Signing secret for this webhook" value={secret} onDone={() => setSecret(null)} />}
        <ul className="flex flex-col gap-2">
          {hooks.data?.map((h) => (
            <li key={h.id} className="flex flex-col gap-2 rounded border border-line p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-xs">{h.url}</span>
                  <span className="text-xs text-muted">
                    {h.description ? `${h.description} · ` : ""}
                    {h.events.includes("*") ? "all events" : h.events.join(", ")}
                    {h.last_delivery_at ? ` · last sent ${fmtTime(h.last_delivery_at)}` : ""}
                  </span>
                </span>
                <Toggle on={h.enabled} onChange={() => act(api.updateWebhook(h.id, { enabled: !h.enabled }), h.enabled ? "Webhook paused" : "Webhook on")} label={`Webhook ${h.url}`} />
                <Button size="sm" onClick={() => act(api.testWebhook(h.id), "Test sent").then(() => setOpen(h.id))}>Send test</Button>
                <Button size="sm" variant="ghost" onClick={() => setOpen(open === h.id ? null : h.id)}>{open === h.id ? "Hide" : "Deliveries"}</Button>
                <Button size="sm" variant="ghost" onClick={() => confirm("Make a new signing secret? The old one stops working right away.") && api.rotateWebhookSecret(h.id).then((r) => setSecret(r.secret)).catch((e) => notify(errText(e)))}>New secret</Button>
                <Button size="sm" variant="danger" onClick={() => confirm(`Delete the webhook to ${h.url}?`) && act(api.deleteWebhook(h.id), "Webhook deleted")}>Delete</Button>
              </div>
              {h.disabled_reason && !h.enabled && <p className="text-xs text-rec">{h.disabled_reason}</p>}
              {open === h.id && <Deliveries hook={h} />}
            </li>
          ))}
          {hooks.data && !hooks.data.length && <EmptyNote>No webhooks yet.</EmptyNote>}
        </ul>
      </div>
    </Card>
  );
}
