"use client";

import { useState } from "react";
import { Card, PageHeader, PlatformBadge, cx } from "@/components/ui";
import { CALENDAR, DAYS } from "@/lib/data";
import { useStore } from "@/lib/store";

export default function Calendar() {
  const { batches, notify } = useStore();
  const [off, setOff] = useState<Set<number>>(new Set());

  return (
    <>
      <PageHeader
        eyebrow="Stage 06 · Publish"
        title="Calendar"
        description="Every scheduled post across all accounts. Each slot is spread across its accounts with the spacing rule, not posted at the same minute."
      />
      <Card padded={false}>
        <div className="overflow-x-auto">
          <div className="grid min-w-[760px] grid-cols-7 gap-px bg-line">
            {DAYS.map((d, di) => (
              <div key={d} className="flex min-h-[300px] flex-col gap-1.5 bg-surface p-2">
                <h3 className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted">{d}</h3>
                {CALENDAR.map((e, i) => {
                  if (e.day !== di) return null;
                  const batch = batches.find((b) => b.id === e.batch);
                  const disabled = batch?.status === "disabled" || off.has(i);
                  return (
                    <button
                      key={i}
                      onClick={() => {
                        const next = new Set(off);
                        if (next.has(i)) next.delete(i);
                        else next.add(i);
                        setOff(next);
                        notify(next.has(i) ? `Switched off: ${e.clip} on ${d} ${e.time}` : `Switched on: ${e.clip} on ${d} ${e.time}`);
                      }}
                      disabled={batch?.status === "disabled"}
                      title={batch?.status === "disabled" ? `Batch ${e.batch} is disabled` : "Click to switch this post off or on"}
                      className={cx(
                        "flex flex-col gap-0.5 rounded px-2 py-1.5 text-left text-xs transition-colors",
                        disabled ? "bg-paper text-muted line-through" : "bg-accent-soft hover:ring-1 hover:ring-accent",
                      )}
                    >
                      <span className="flex items-center gap-1 font-mono text-[11px]">
                        {e.time} <PlatformBadge platform={e.platform} /> ×{e.count}
                      </span>
                      <span className="font-medium">{e.clip}</span>
                      <span className="font-mono text-[10px] text-muted">{e.batch}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </Card>
      <p className="text-sm text-muted">Crossed-out posts are switched off, or belong to a disabled batch. Drag-and-drop rescheduling comes with the backend.</p>
    </>
  );
}
