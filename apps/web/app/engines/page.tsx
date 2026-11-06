"use client";

import { Badge, Button, Card, Dot, PageHeader, cx } from "@/components/ui";
import { CONNECTIONS, ENGINES, STAGES } from "@/lib/data";
import { useStore } from "@/lib/store";

export default function Engines() {
  const { engines, setEngine, notify } = useStore();

  const chosen = STAGES.map((s) => ({ stage: s, engine: ENGINES[s.id].find((e) => e.id === engines[s.id]) ?? ENGINES[s.id][0] }));
  const total = chosen.reduce((sum, { engine }) => {
    const m = engine.cost?.match(/\$([\d.]+)/);
    return sum + (m ? parseFloat(m[1]) : 0);
  }, 0);

  return (
    <>
      <PageHeader
        eyebrow="Plugins"
        title="Engines & connectors"
        description="Choose what runs each stage. Free engines are open source. Connectors use your own vendor accounts, and you pay the vendor directly."
      />

      <div className="flex flex-wrap gap-2 text-xs">
        <Badge tone="free">Free / open source</Badge>
        <Badge tone="paid">Connector · your account</Badge>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-3">
          {STAGES.map((s, i) => (
            <Card key={s.id}>
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                  <h3 className="font-semibold">{s.name}</h3>
                  <span className="text-sm text-muted">{s.output}</span>
                </div>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={`Engine for ${s.name}`}>
                  {ENGINES[s.id].map((e) => {
                    const on = engines[s.id] === e.id;
                    return (
                      <button
                        key={e.id}
                        role="radio"
                        aria-checked={on}
                        onClick={() => setEngine(s.id, e.id)}
                        className={cx(
                          "flex min-w-[150px] flex-col gap-0.5 rounded border px-3 py-2 text-left text-sm transition-colors",
                          on ? "border-accent bg-accent-soft" : "border-line hover:border-ink/40",
                        )}
                      >
                        <span className="flex items-center gap-1.5 font-medium">
                          <span className={cx("h-2 w-2 rounded-full", e.kind === "free" ? "bg-free" : "bg-paid")} aria-hidden />
                          {e.name}
                        </span>
                        <span className="text-xs text-muted">
                          {e.note}
                          {e.cost ? ` · ${e.cost}` : ""}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </Card>
          ))}
        </div>

        <div className="flex flex-col gap-4 lg:sticky lg:top-6 lg:self-start">
          <Card title="Run preview">
            <table className="w-full text-sm">
              <tbody>
                {chosen.map(({ stage, engine }) => (
                  <tr key={stage.id} className="border-b border-line last:border-0">
                    <td className="py-1.5 text-muted">{stage.name}</td>
                    <td className="py-1.5">
                      <Badge tone={engine.kind === "free" ? "free" : "paid"}>{engine.name}</Badge>
                    </td>
                    <td className="tnum py-1.5 text-right font-mono text-xs">{engine.cost ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex items-baseline justify-between border-t border-line pt-3">
              <span className="text-sm font-semibold">Estimated for a 60-min video</span>
              <span className="tnum font-mono font-bold">${total.toFixed(2)}</span>
            </div>
            <p className="mt-2 text-xs text-muted">Example figures. Real estimates come from each vendor&apos;s current pricing. Per-minute vendors are billed by them.</p>
          </Card>

          <Card title="Your connections" padded={false}>
            <ul className="divide-y divide-line text-sm">
              {CONNECTIONS.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-2 px-5 py-2.5">
                  <span className="min-w-0">
                    <span className="block font-medium">{c.name}</span>
                    <span className="block text-xs text-muted">{c.usedFor}</span>
                  </span>
                  {c.status === "connected" ? (
                    <span className="flex items-center gap-1.5 text-xs"><Dot tone="ok" /> Connected</span>
                  ) : (
                    <Button size="sm" onClick={() => notify(`Connect ${c.name}: key is stored encrypted (prototype)`)}>
                      {c.status === "reconnect" ? "Reconnect" : "Connect"}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
