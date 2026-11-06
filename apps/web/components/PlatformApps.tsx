"use client";

import { useState } from "react";
import { CheckCircle2, Copy, ExternalLink } from "lucide-react";
import { api, type ApiPlatformApp } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";
import { Badge, Button, Card, PlatformBadge } from "./ui";

export function PlatformApps() {
  const apps = usePoll(api.platforms, { intervalMs: 60000 });
  return (
    <Card title="Platform apps" className="lg:col-span-2">
      <div id="platform-apps" className="flex flex-col gap-3 text-sm">
        <p className="text-muted">
          To post to a platform, register your own developer app with it and paste its keys here (one app per platform, used for all your accounts on it). Secrets are stored encrypted and never shown again. Step-by-step guide:{" "}
          <span className="font-mono text-xs">docs/PLATFORM_SETUP.md</span>.
        </p>
        {apps.error && <p className="text-rec">{apps.error}</p>}
        <div className="flex flex-col divide-y divide-line rounded border border-line">
          {(apps.data ?? []).map((p) => (
            <AppRow key={p.platform} app={p} onSaved={apps.refresh} />
          ))}
        </div>
      </div>
    </Card>
  );
}

function AppRow({ app, onSaved }: { app: ApiPlatformApp; onSaved: () => void }) {
  const { notify } = useStore();
  const [open, setOpen] = useState(false);
  const [id, setId] = useState(app.client_id ?? "");
  const [secret, setSecret] = useState("");

  async function save() {
    try {
      await api.savePlatformApp(app.platform, id.trim(), secret.trim());
      notify(`${app.label} app saved`);
      setSecret("");
      setOpen(false);
      onSaved();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(app.redirect_uri);
      notify("Redirect address copied");
    } catch {
      notify("Copy failed; select the address and copy it by hand");
    }
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-semibold">
          <PlatformBadge platform={app.platform} /> {app.label}
          {app.configured ? (
            <Badge tone="free">
              <CheckCircle2 size={12} /> Keys saved
            </Badge>
          ) : (
            <Badge>Not set up</Badge>
          )}
        </span>
        <span className="flex gap-2">
          <a href={app.docs_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent">
            Platform docs <ExternalLink size={12} />
          </a>
          <Button size="sm" onClick={() => setOpen(!open)}>
            {open ? "Close" : app.configured ? "Change keys" : "Add keys"}
          </Button>
        </span>
      </div>
      {open && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted">Redirect address to enter in your {app.label} app settings</span>
            <span className="flex items-center gap-2">
              <code className="min-w-0 flex-1 select-all break-all rounded bg-paper px-2 py-1.5 text-xs">{app.redirect_uri}</code>
              <Button size="sm" variant="ghost" onClick={copy} aria-label="Copy redirect address">
                <Copy size={14} />
              </Button>
            </span>
            <span className="text-xs text-muted">Permissions to request: {app.scopes.join(", ")}</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label htmlFor={`cid-${app.platform}`} className="flex flex-col gap-1">
              <span className="text-xs text-muted">{app.client_id_label}</span>
              <input id={`cid-${app.platform}`} value={id} onChange={(e) => setId(e.target.value)} autoComplete="off" className="rounded border border-line bg-paper px-3 py-2 font-mono text-xs" />
            </label>
            <label htmlFor={`sec-${app.platform}`} className="flex flex-col gap-1">
              <span className="text-xs text-muted">Secret</span>
              <input id={`sec-${app.platform}`} type="password" value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="new-password" placeholder={app.configured ? "Enter a new secret to replace it" : ""} className="rounded border border-line bg-paper px-3 py-2 font-mono text-xs" />
            </label>
          </div>
          <span className="flex gap-2">
            <Button size="sm" variant="primary" disabled={!id.trim() || !secret.trim()} onClick={save}>
              Save {app.label} keys
            </Button>
            {app.configured && (
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  await api.deletePlatformApp(app.platform);
                  notify(`${app.label} keys removed`);
                  onSaved();
                }}
              >
                Remove keys
              </Button>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
