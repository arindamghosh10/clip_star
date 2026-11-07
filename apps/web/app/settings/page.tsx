"use client";

import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { BackupsCard, NotificationsCard, ProfileCard, StorageCard, TeamCard, WorkspaceCard } from "@/components/AdminSettings";
import { ApiKeysCard, WebhooksCard } from "@/components/Integrations";
import { MusicLibraryCard } from "@/components/MusicLibrary";
import { PlatformApps } from "@/components/PlatformApps";
import { Button, Card, PageHeader, Toggle, cx } from "@/components/ui";
import { API_BASE, PLATFORM_RULES, api, type PlatformId, type WorkspaceSettings } from "@/lib/api";
import { useStore } from "@/lib/store";

const DEFAULTS: Required<Omit<WorkspaceSettings, "auto_approve_score" | "default_music_id" | "music_volume">> & { auto_approve_score: number | null } = {
  niche: "",
  voice: "",
  audience: "",
  banned_topics: [],
  hashtags: [],
  cta: "Follow for more.",
  clip_min_s: 15,
  clip_max_s: 60,
  clip_target_s: 40,
  max_clips: 8,
  variants: 2,
  caption_style: "bold-pop",
  platforms: Object.keys(PLATFORM_RULES) as PlatformId[],
  auto_approve_score: null,
  spacing_minutes: 45,
  duplicate_warning_accounts: 5,
  quiet_hours: true,
  auto_reply_categories: [],
  auto_hide_spam: false,
  replies_per_hour: 20,
  lead_reply: "Thanks for reaching out! The best way to contact me is the link in my bio.",
  comment_sync_minutes: 15,
  auto_zoom: true,
  emojis: false,
  broll: false,
};

// Only the keys this page edits (workspace settings also hold things like the learned model and budgets).
const pick = (w: Record<string, unknown>) => Object.fromEntries(Object.keys(DEFAULTS).map((k) => [k, k in w ? w[k] : DEFAULTS[k as keyof typeof DEFAULTS]])) as typeof DEFAULTS;

const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export default function Settings() {
  const { notify } = useStore();
  const [saved, setSaved] = useState<typeof DEFAULTS | null>(null);
  const [f, setF] = useState<typeof DEFAULTS>(DEFAULTS);
  const [text, setText] = useState({ banned: "", tags: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .workspace()
      .then((w) => {
        const v = pick(w.settings as Record<string, unknown>);
        setSaved(v);
        setF(v);
        setText({ banned: v.banned_topics.join(", "), tags: v.hashtags.map((h) => `#${h}`).join(", ") });
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const set = <K extends keyof typeof DEFAULTS>(k: K, v: (typeof DEFAULTS)[K]) => setF((x) => ({ ...x, [k]: v }));
  const current = { ...f, banned_topics: list(text.banned), hashtags: list(text.tags).map((h) => h.replace(/^#+/, "")) };
  const dirty = saved !== null && JSON.stringify(current) !== JSON.stringify(saved);
  const lengthError = f.clip_min_s >= f.clip_max_s ? "The shortest clip must be shorter than the longest." : null;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const w = await api.updateWorkspace({ settings: current });
      const v = pick(w.settings as Record<string, unknown>);
      setSaved(v);
      setF(v);
      notify("Settings saved. They apply to the next videos you process.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!saved && !error) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="Your creator profile, clip rules and post defaults. Every engine reads these."
        actions={
          <Button variant="primary" disabled={!dirty || busy || !!lengthError} onClick={save}>
            {dirty ? "Save changes" : "Saved"}
          </Button>
        }
      />
      {error && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Creator profile">
          <div className="flex flex-col gap-3 text-sm">
            <Text id="niche" label="Niche" value={f.niche} onChange={(v) => set("niche", v)} placeholder="Personal finance for renters" />
            <Text id="voice" label="Voice" value={f.voice} onChange={(v) => set("voice", v)} placeholder="Friendly, direct, short sentences, no jargon" />
            <Text id="audience" label="Audience" value={f.audience} onChange={(v) => set("audience", v)} placeholder="Renters aged 20-35" />
            <Text id="banned" label="Never post about (comma separated)" value={text.banned} onChange={(v) => setText({ ...text, banned: v })} placeholder="crypto, politics" />
          </div>
        </Card>

        <Card title="Clips">
          <div className="flex flex-col gap-4 text-sm">
            <div className="grid grid-cols-3 gap-3">
              <Num id="min" label="Shortest (s)" value={f.clip_min_s} min={5} max={170} onChange={(v) => set("clip_min_s", v)} />
              <Num id="target" label="Ideal (s)" value={f.clip_target_s} min={5} max={180} onChange={(v) => set("clip_target_s", v)} />
              <Num id="max" label="Longest (s)" value={f.clip_max_s} min={10} max={180} onChange={(v) => set("clip_max_s", v)} />
            </div>
            {lengthError && <p className="text-xs text-rec">{lengthError}</p>}
            <Num id="maxclips" label="Clips per video, at most" value={f.max_clips} min={1} max={30} onChange={(v) => set("max_clips", v)} />
            <Field label="Versions per clip">
              <Choice value={String(f.variants)} options={[["1", "One"], ["2", "Two (A/B test)"]]} onChange={(v) => set("variants", Number(v) as 1 | 2)} />
            </Field>
            <label className="flex items-center justify-between gap-3">
              <span>Zoom in on key words (numbers, “never”, “secret”…)</span>
              <Toggle on={f.auto_zoom} onChange={() => set("auto_zoom", !f.auto_zoom)} label="Zoom in on key words" />
            </label>
            <label className="flex items-center justify-between gap-3">
              <span>Emojis above the captions (a few per clip)</span>
              <Toggle on={f.emojis} onChange={() => set("emojis", !f.emojis)} label="Emojis" />
            </label>
            <label className="flex items-center justify-between gap-3">
              <span>
                B-roll cutaways from Pexels (up to two per clip)
                <span className="block text-xs text-muted">Needs a free Pexels API key on the server (CLIPSTAR_PEXELS_API_KEY).</span>
              </span>
              <Toggle on={f.broll} onChange={() => set("broll", !f.broll)} label="B-roll" />
            </label>
            <Field label="Caption style for version A">
              <Choice value={f.caption_style} options={[["bold-pop", "Bold, word highlight"], ["clean", "Clean, boxed"]]} onChange={(v) => set("caption_style", v as "bold-pop" | "clean")} />
            </Field>
          </div>
        </Card>

        <Card title="Posts">
          <div className="flex flex-col gap-3 text-sm">
            <Field label="Platforms to write captions for">
              <div className="flex flex-wrap gap-2">
                {(Object.keys(PLATFORM_RULES) as PlatformId[]).map((p) => {
                  const on = f.platforms.includes(p);
                  return (
                    <button
                      key={p}
                      aria-pressed={on}
                      onClick={() => set("platforms", on ? (f.platforms.length > 1 ? f.platforms.filter((x) => x !== p) : f.platforms) : [...f.platforms, p])}
                      className={cx("rounded-full border px-3 py-1 text-xs font-semibold", on ? "border-ink bg-ink text-paper" : "border-line text-muted")}
                    >
                      {PLATFORM_RULES[p].label}
                    </button>
                  );
                })}
              </div>
            </Field>
            <Text id="tags" label="Hashtags to always use (comma separated)" value={text.tags} onChange={(v) => setText({ ...text, tags: v })} placeholder="#moneytips, #renting" />
            <Text id="cta" label="Call to action" value={f.cta} onChange={(v) => set("cta", v)} placeholder="Follow for part 2." />
          </div>
        </Card>

        <Card title="Approvals">
          <div className="flex flex-col gap-3 text-sm">
            <label className="flex items-center justify-between gap-3">
              <span>Auto-approve high-scoring clips</span>
              <Toggle on={f.auto_approve_score !== null} onChange={() => set("auto_approve_score", f.auto_approve_score === null ? 85 : null)} label="Auto-approve high-scoring clips" />
            </label>
            {f.auto_approve_score !== null && <Num id="auto" label="Approve automatically at this score or above" value={f.auto_approve_score} min={1} max={100} onChange={(v) => set("auto_approve_score", v)} />}
            <p className="text-muted">Publishing always needs one approval per batch, and you can disable any batch at any time.</p>
          </div>
        </Card>

        <Card title="Publishing safety defaults" className="lg:col-span-2">
          <div className="grid gap-4 text-sm sm:grid-cols-3">
            <Num id="spacing" label="Minutes between accounts posting the same clip" value={f.spacing_minutes} min={0} max={1440} onChange={(v) => set("spacing_minutes", v)} />
            <Num id="dupwarn" label="Warn when one unvaried clip goes to more than this many accounts" value={f.duplicate_warning_accounts} min={1} max={500} onChange={(v) => set("duplicate_warning_accounts", v)} />
            <label className="flex items-center justify-between gap-3">
              <span>Respect quiet hours in each account&apos;s time zone</span>
              <Toggle on={f.quiet_hours} onChange={() => set("quiet_hours", !f.quiet_hours)} label="Quiet hours" />
            </label>
          </div>
          <p className="mt-3 text-xs text-muted">The scheduler and publisher use these for every batch.</p>
        </Card>
        <MusicLibraryCard />
        <PlatformApps />
        <WorkspaceCard />
        <ProfileCard />
        <NotificationsCard />
        <TeamCard />
        <StorageCard />
        <BackupsCard />
        <h2 id="integrations" className="-mb-1 mt-2 font-mono text-xs uppercase tracking-wider text-muted lg:col-span-2">Integrations</h2>
        <ApiKeysCard />
        <McpCard />
        <WebhooksCard />
      </div>
    </>
  );
}

function McpCard() {
  return (
    <Card title="AI assistants (MCP)">
      <div className="flex flex-col gap-2 text-sm">
        <p className="text-muted">
          Let Claude or another MCP-capable assistant review clips, schedule posts and read results for you. It can only do what its API key allows, and it asks before publishing or replying.
        </p>
        <ol className="flex list-decimal flex-col gap-1 pl-5">
          <li>Create an API key (Editor for full use, Viewer to only look).</li>
          <li>Install the server: <code className="font-mono text-xs">pip install ./integrations/mcp</code></li>
          <li>
            Add it to your assistant, e.g. Claude Code:
            <code className="mt-1 block break-all rounded bg-paper px-2 py-1 font-mono text-xs">claude mcp add clipstar --env CLIPSTAR_URL={API_BASE || (typeof window !== "undefined" ? window.location.origin : "http://localhost:3000")} --env CLIPSTAR_API_KEY=cs_… -- clipstar-mcp</code>
          </li>
        </ol>
        <p className="text-xs text-muted">Other assistants and the tool list: docs/API.md.</p>
      </div>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-muted">{label}</span>
      {children}
    </div>
  );
}

function Text({ id, label, value, onChange, placeholder }: { id: string; label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="text-muted">{label}</span>
      <input id={id} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className="rounded border border-line bg-paper px-3 py-2" />
    </label>
  );
}

function Num({ id, label, value, min, max, onChange }: { id: string; label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="text-muted">{label}</span>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(Math.max(min, Math.min(max, n)));
        }}
        className="tnum w-full rounded border border-line bg-paper px-3 py-2"
      />
    </label>
  );
}

function Choice({ value, options, onChange }: { value: string; options: [string, string][]; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="radiogroup">
      {options.map(([v, l]) => (
        <button key={v} role="radio" aria-checked={value === v} onClick={() => onChange(v)} className={cx("rounded border px-3 py-2", value === v ? "border-accent bg-accent-soft" : "border-line")}>
          {l}
        </button>
      ))}
    </div>
  );
}
