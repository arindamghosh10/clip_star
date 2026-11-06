"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Check, CircleAlert } from "lucide-react";
import { useAuth } from "@/components/Auth";
import { FormError, Input, errText } from "@/components/Form";
import { Badge, Button, cx } from "@/components/ui";
import { api, type ApiAccount, type ApiEngine } from "@/lib/api";

const STEPS = ["Your account", "Creator profile", "Engines", "Accounts", "First video"];

function Steps({ at }: { at: number }) {
  return (
    <ol className="flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Setup steps">
      {STEPS.map((s, i) => (
        <li key={s} className={cx("flex items-center gap-1.5", i === at ? "font-semibold text-ink" : "text-muted")} aria-current={i === at ? "step" : undefined}>
          <span className={cx("flex h-5 w-5 items-center justify-center rounded-full font-mono text-[10px]", i < at ? "bg-free text-white" : i === at ? "bg-ink text-paper" : "bg-line")}>
            {i < at ? <Check size={12} /> : i + 1}
          </span>
          {s}
        </li>
      ))}
    </ol>
  );
}

function Shell({ at, title, description, children }: { at: number; title: string; description: ReactNode; children: ReactNode }) {
  return (
    <section className="flex w-full max-w-xl flex-col gap-5 rounded-md border border-line bg-surface p-6">
      <Steps at={at} />
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        <p className="text-sm text-muted">{description}</p>
      </div>
      {children}
    </section>
  );
}

function Owner({ tokenRequired, onDone }: { tokenRequired: boolean; onDone: () => void }) {
  const [f, setF] = useState({ name: "", email: "", password: "", workspace_name: "", token: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.setup({ name: f.name, email: f.email, password: f.password, workspace_name: f.workspace_name || `${f.name}'s workspace` }, f.token || undefined);
      onDone();
    } catch (err) {
      setError(errText(err));
      setBusy(false);
    }
  }
  return (
    <Shell at={0} title="Welcome to clip_star" description="Create the owner account. The owner manages the team, platform apps, paid engines, budgets and backups. You can invite others later.">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <Input id="name" label="Your name" required autoComplete="name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <Input id="ws" label="Workspace name" placeholder="e.g. Maya Money" value={f.workspace_name} onChange={(e) => setF({ ...f, workspace_name: e.target.value })} />
        <div className="sm:col-span-2">
          <Input id="email" label="Email" type="email" required autoComplete="username" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </div>
        <div className="sm:col-span-2">
          <Input id="pw" label="Password" type="password" required minLength={10} autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} hint="At least 10 characters." />
        </div>
        {tokenRequired && (
          <div className="sm:col-span-2">
            <Input id="token" label="Server API token" type="password" required value={f.token} onChange={(e) => setF({ ...f, token: e.target.value })} hint="This server has CLIPSTAR_API_TOKEN set. Enter it once to prove you run this server." />
          </div>
        )}
        <div className="sm:col-span-2">
          <FormError error={error} />
        </div>
        <Button variant="primary" type="submit" disabled={busy} className="sm:col-span-2">
          {busy ? "Creating…" : "Create owner account"}
        </Button>
      </form>
    </Shell>
  );
}

function Profile({ next }: { next: () => void }) {
  const [f, setF] = useState({ niche: "", voice: "", audience: "", clip_target_s: 40 });
  const [loadedTarget, setLoadedTarget] = useState(40);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.workspace().then((w) => {
      const t = w.settings.clip_target_s ?? 40;
      setLoadedTarget(t);
      setF({ niche: w.settings.niche ?? "", voice: w.settings.voice ?? "", audience: w.settings.audience ?? "", clip_target_s: t });
    });
  }, []);
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const target = Math.max(15, Math.min(90, f.clip_target_s));
      // only touch clip lengths if the ideal length was changed here
      const lengths = target !== loadedTarget ? { clip_target_s: target, clip_min_s: Math.max(5, target - 25), clip_max_s: Math.min(180, target + 20) } : {};
      await api.updateWorkspace({ settings: { niche: f.niche, voice: f.voice, audience: f.audience, ...lengths } });
      next();
    } catch (err) {
      setError(errText(err));
    }
  }
  return (
    <Shell at={1} title="Tell clip_star about your content" description="Every engine uses this to pick moments and write post text in your voice. You can change it any time in Settings.">
      <form onSubmit={save} className="flex flex-col gap-3">
        <Input id="niche" label="What is your channel about?" placeholder="Personal finance for renters" value={f.niche} onChange={(e) => setF({ ...f, niche: e.target.value })} />
        <Input id="voice" label="How do you talk?" placeholder="Friendly, direct, short sentences" value={f.voice} onChange={(e) => setF({ ...f, voice: e.target.value })} />
        <Input id="aud" label="Who watches?" placeholder="Renters aged 20-35" value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })} />
        <Input id="len" label="Ideal clip length (seconds)" type="number" min={15} max={90} value={f.clip_target_s} onChange={(e) => setF({ ...f, clip_target_s: Number(e.target.value) || 40 })} />
        <FormError error={error} />
        <div className="flex justify-between gap-2">
          <Button type="button" variant="ghost" onClick={next}>Skip</Button>
          <Button variant="primary" type="submit">Save and continue</Button>
        </div>
      </form>
    </Shell>
  );
}

const STAGE_NAME: Record<string, string> = { understand: "Transcription", moments: "Finding moments", package: "Post text", engage: "Comments" };

function Engines({ next, back }: { next: () => void; back: () => void }) {
  const [engines, setEngines] = useState<ApiEngine[] | null>(null);
  useEffect(() => {
    api.engines().then(setEngines).catch(() => setEngines([]));
  }, []);
  const chosen = (engines ?? []).filter((e) => e.selected);
  return (
    <Shell at={2} title="Engines" description="Free engines run on this server and are already chosen. Paid connectors (like Claude) use your own API key and are optional.">
      <ul className="flex flex-col gap-2 text-sm">
        {!engines && <li className="text-muted">Checking…</li>}
        {chosen.map((e) => (
          <li key={e.stage + e.id} className="flex items-start gap-2 rounded border border-line p-3">
            {e.ok ? <Check size={16} className="mt-0.5 text-free" /> : <CircleAlert size={16} className="mt-0.5 text-gate" />}
            <span className="min-w-0 flex-1">
              <span className="font-semibold">{STAGE_NAME[e.stage] ?? e.stage}:</span> {e.name} <Badge tone={e.kind === "free" ? "free" : "paid"}>{e.kind === "free" ? "free" : "paid"}</Badge>
              <span className="block text-xs text-muted">{e.message}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">
        To use a paid engine, set its key on the server (for Claude: CLIPSTAR_ANTHROPIC_API_KEY) and pick it in <Link href="/engines" className="text-accent">Engines & connectors</Link>. You can set a monthly budget there too.
      </p>
      <div className="flex justify-between gap-2">
        <Button variant="ghost" onClick={back}>Back</Button>
        <Button variant="primary" onClick={next}>Continue</Button>
      </div>
    </Shell>
  );
}

function Accounts({ next, back }: { next: () => void; back: () => void }) {
  const [accounts, setAccounts] = useState<ApiAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.accounts().then(setAccounts).catch((e) => setError(errText(e)));
  useEffect(() => {
    load();
  }, []);
  async function practice() {
    try {
      await api.createAccount({ platform: "instagram", handle: "@practice", group_name: "Practice" });
      load();
    } catch (e) {
      setError(errText(e));
    }
  }
  return (
    <Shell at={3} title="Social accounts" description="Connect the accounts clips will be posted from. Each platform needs a developer app once (Settings → Platform apps); then every account logs in with its own login.">
      <div className="flex flex-col gap-2 text-sm">
        {accounts?.length ? (
          <p>
            <Check size={14} className="mr-1 inline text-free" />
            {accounts.length} account{accounts.length === 1 ? "" : "s"} added.
          </p>
        ) : (
          <p className="text-muted">No accounts yet.</p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          <button onClick={practice} className="rounded border border-line p-3 text-left hover:border-accent">
            <span className="font-semibold">Add a practice account</span>
            <span className="block text-xs text-muted">Goes through scheduling and publishing like a real one, but nothing is posted. Good for trying things out.</span>
          </button>
          <Link href="/settings#platform-apps" className="rounded border border-line p-3 hover:border-accent">
            <span className="font-semibold">Set up a real platform</span>
            <span className="block text-xs text-muted">Add the developer app keys, then connect accounts on the Accounts screen.</span>
          </Link>
        </div>
        <FormError error={error} />
      </div>
      <div className="flex justify-between gap-2">
        <Button variant="ghost" onClick={back}>Back</Button>
        <Button variant="primary" onClick={next}>Continue</Button>
      </div>
    </Shell>
  );
}

function FirstVideo({ back }: { back: () => void }) {
  const router = useRouter();
  const { refresh } = useAuth();
  const [error, setError] = useState<string | null>(null);
  async function finish(to: string) {
    try {
      await api.updateWorkspace({ settings: { setup_done: true } });
      await refresh();
      router.replace(to);
    } catch (e) {
      setError(errText(e));
    }
  }
  return (
    <Shell at={4} title="You're ready" description="Add your first long video. clip_star transcribes it, finds the best moments, cuts 9:16 clips with captions and writes post text for each platform. You approve before anything is posted.">
      <ul className="flex flex-col gap-1.5 text-sm text-muted">
        <li>• Invite your team in Settings → Team (editors, reviewers or viewers).</li>
        <li>• Set up email alerts in Settings → Notifications.</li>
        <li>• Backups run daily in Docker; download one in Settings → Backups and keep it somewhere safe.</li>
      </ul>
      <FormError error={error} />
      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="ghost" onClick={back}>Back</Button>
        <span className="flex gap-2">
          <Button onClick={() => finish("/")}>Go to overview</Button>
          <Button variant="primary" onClick={() => finish("/videos")}>Add a video</Button>
        </span>
      </div>
    </Shell>
  );
}

function Wizard() {
  const { state, refresh } = useAuth();
  const params = useSearchParams();
  const router = useRouter();
  const step = Math.max(0, Math.min(4, Number(params.get("step") ?? (state?.setup_required ? 0 : 1)) || 0));
  const go = (n: number) => router.replace(`/setup?step=${n}`);

  if (!state) return null;
  if (state.setup_required) return <Owner tokenRequired={state.token_required} onDone={() => refresh().then(() => go(1))} />;
  if (state.user && state.user.role !== "owner") {
    return (
      <Shell at={step} title="Setup is done by the owner" description="Ask the owner of this workspace to finish setting up.">
        <Link href="/" className="text-sm text-accent">Back to clip_star</Link>
      </Shell>
    );
  }
  if (step <= 1) return <Profile next={() => go(2)} />;
  if (step === 2) return <Engines next={() => go(3)} back={() => go(1)} />;
  if (step === 3) return <Accounts next={() => go(4)} back={() => go(2)} />;
  return <FirstVideo back={() => go(3)} />;
}

export default function Page() {
  return (
    <Suspense>
      <Wizard />
    </Suspense>
  );
}
