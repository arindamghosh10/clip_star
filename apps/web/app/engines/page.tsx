"use client";

import { AlertTriangle } from "lucide-react";
import { BudgetCard } from "@/components/AdminSettings";
import { Badge, Card, PageHeader, cx } from "@/components/ui";
import { STAGES } from "@/lib/data";
import { api, type ApiEngine } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

// Stages that run on built-in tools today (no choice to make yet).
const BUILT_IN: Record<string, string> = {
  ingest: "FFmpeg (built in): checks the file, makes a 720p preview copy and extracts audio.",
  edit: "FFmpeg + OpenCV (built in): vertical reframing, word-by-word captions, hook title, zooms and emojis, your music (ducked under speech), loudness levelling. Optional: B-roll from Pexels and dubbing with ElevenLabs (your keys).",
  publish: "Official platform APIs (built in): YouTube, Instagram, Facebook, Threads, TikTok, X, LinkedIn, Pinterest. Set up in Settings → Platform apps.",
  measure: "Official platform APIs (built in): views, watch time, shares and follows, 1 hour to 7 days after each post.",
  learn: "Built in: insights, weekly reports and a per-creator scoring model that only switches on when it beats the built-in rules.",
};

export default function Engines() {
  const { notify } = useStore();
  const engines = usePoll(api.engines, { intervalMs: 30000 });

  async function pick(e: ApiEngine) {
    if (e.selected) return;
    try {
      engines.setData(await api.selectEngine(e.stage, e.id));
      notify(`${e.name} now runs ${STAGES.find((s) => s.id === e.stage)?.name}`);
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Plugins"
        title="Engines & connectors"
        description="Choose what runs each stage. Free engines are open source or built in. Connectors use your own accounts, and you pay the provider directly."
      />
      <BudgetCard />
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge tone="free">Free</Badge>
        <Badge tone="paid">Connector · your account</Badge>
      </div>
      {engines.error && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {engines.error}
        </p>
      )}
      <div className="flex flex-col gap-3">
        {STAGES.map((s, i) => {
          const list = (engines.data ?? []).filter((e) => e.stage === s.id);
          return (
            <Card key={s.id}>
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                  <h2 className="font-semibold">{s.name}</h2>
                  <span className="text-sm text-muted">{s.output}</span>
                </div>
                {list.length === 0 ? (
                  <p className="text-sm text-muted">{BUILT_IN[s.id] ?? "Built in."}</p>
                ) : (
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="radiogroup" aria-label={`Engine for ${s.name}`}>
                    {list.map((e) => (
                      <button
                        key={e.id}
                        role="radio"
                        aria-checked={e.selected}
                        onClick={() => pick(e)}
                        className={cx("flex flex-col gap-1 rounded border p-3 text-left text-sm transition-colors", e.selected ? "border-accent bg-accent-soft" : "border-line hover:border-ink/40")}
                      >
                        <span className="flex items-center gap-2 font-semibold">
                          <span className={cx("h-2 w-2 rounded-full", e.kind === "free" ? "bg-free" : "bg-paid")} aria-hidden />
                          {e.name}
                          {e.selected && <Badge tone="accent">In use</Badge>}
                        </span>
                        <span className="text-muted">{e.description}</span>
                        <span className={cx("text-xs", e.ok ? "text-free" : "text-paid")}>
                          {e.ok ? "✓ Ready" : "Needs setup"}
                          {e.message ? ` · ${e.message}` : ""}
                        </span>
                        {e.estimate && <span className="text-xs text-muted">Cost: {e.estimate}</span>}
                      </button>
                    ))}
                  </div>
                )}
                {list.some((e) => e.selected && !e.ok) && (
                  <p className="text-xs text-paid">
                    {s.id === "understand"
                      ? "The selected engine isn't set up. Videos uploaded with a captions file still work; others will stop at this step until it is."
                      : "The selected engine isn't set up, so the free built-in engine runs instead until it is."}
                  </p>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}
