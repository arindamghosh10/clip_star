"use client";

import { useState } from "react";
import { Button, Card, PageHeader, Toggle } from "@/components/ui";
import { useStore } from "@/lib/store";

export default function Settings() {
  const { notify } = useStore();
  const [captionStyle, setCaptionStyle] = useState("bold-pop");
  const [safety, setSafety] = useState({ spacing: 45, dupWarn: 5, quiet: true });
  const [autoApprove, setAutoApprove] = useState(false);

  return (
    <>
      <PageHeader eyebrow="Workspace" title="Settings" description="Your creator profile, brand kit and publishing safety defaults. Every agent reads these." />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Creator profile">
          <div className="flex flex-col gap-3 text-sm">
            <Field id="niche" label="Niche" defaultValue="Personal finance, renting, budgeting" />
            <Field id="voice" label="Voice" defaultValue="Friendly, direct, a little funny. Short sentences. No jargon." />
            <Field id="avoid" label="Topics to avoid" defaultValue="Crypto tips, specific stock picks" />
            <Field id="audience" label="Audience" defaultValue="Renters aged 20–35 in the US, UK and India" />
          </div>
        </Card>

        <Card title="Brand kit">
          <div className="flex flex-col gap-4 text-sm">
            <div className="flex flex-col gap-1.5">
              <span className="text-muted">Caption style</span>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Caption style">
                {[
                  { id: "bold-pop", label: "Bold pop", cls: "font-extrabold uppercase" },
                  { id: "clean", label: "Clean", cls: "font-medium" },
                  { id: "highlight", label: "Highlight word", cls: "font-bold" },
                ].map((s) => (
                  <button
                    key={s.id}
                    role="radio"
                    aria-checked={captionStyle === s.id}
                    onClick={() => setCaptionStyle(s.id)}
                    className={`rounded border px-3 py-2 ${captionStyle === s.id ? "border-accent bg-accent-soft" : "border-line"}`}
                  >
                    <span className={s.cls}>{s.label}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-muted">Brand colours</span>
              <div className="flex gap-2">
                {["#2C47CF", "#D93A2B", "#14202A", "#F6C343"].map((c) => (
                  <span key={c} className="flex flex-col items-center gap-1">
                    <span className="h-8 w-8 rounded border border-line" style={{ background: c }} />
                    <span className="font-mono text-[10px] text-muted">{c}</span>
                  </span>
                ))}
              </div>
            </div>
            <Button className="self-start" onClick={() => notify("Logo, fonts, intro and outro upload (prototype)")}>Upload logo, fonts, intro/outro</Button>
          </div>
        </Card>

        <Card title="Approvals">
          <div className="flex flex-col gap-3 text-sm">
            <label className="flex items-center justify-between gap-3">
              <span>Auto-approve clips scoring 90 or more</span>
              <Toggle on={autoApprove} onChange={() => setAutoApprove(!autoApprove)} label="Auto-approve high-scoring clips" />
            </label>
            <p className="text-muted">Publishing always needs one approval per batch. You can disable any batch at any time.</p>
          </div>
        </Card>

        <Card title="Publishing safety defaults">
          <div className="flex flex-col gap-4 text-sm">
            <Range
              id="spacing"
              label="Minimum gap between accounts posting the same clip"
              value={safety.spacing}
              min={0}
              max={180}
              unit="min"
              onChange={(v) => setSafety({ ...safety, spacing: v })}
            />
            <Range
              id="dupwarn"
              label="Warn when one unvaried clip goes to more than"
              value={safety.dupWarn}
              min={1}
              max={30}
              unit="accounts"
              onChange={(v) => setSafety({ ...safety, dupWarn: v })}
            />
            <label className="flex items-center justify-between gap-3">
              <span>Respect quiet hours in each account&apos;s time zone</span>
              <Toggle on={safety.quiet} onChange={() => setSafety({ ...safety, quiet: !safety.quiet })} label="Quiet hours" />
            </label>
            <p className="text-xs text-muted">Everything posts through each platform&apos;s official API and stays under its limits.</p>
          </div>
        </Card>
      </div>
    </>
  );
}

function Field({ id, label, defaultValue }: { id: string; label: string; defaultValue: string }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-1">
      <span className="text-muted">{label}</span>
      <input id={id} defaultValue={defaultValue} className="rounded border border-line bg-paper px-3 py-2" />
    </label>
  );
}

function Range({ id, label, value, min, max, unit, onChange }: { id: string; label: string; value: number; min: number; max: number; unit: string; onChange: (v: number) => void }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-1.5">
      <span className="flex justify-between gap-3">
        <span>{label}</span>
        <span className="tnum shrink-0 font-mono">
          {value} {unit}
        </span>
      </span>
      <input id={id} type="range" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} className="accent-[rgb(var(--accent))]" />
    </label>
  );
}
