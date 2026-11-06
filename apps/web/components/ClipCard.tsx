"use client";

import { Check, Pencil, X } from "lucide-react";
import type { Clip, Platform } from "@/lib/data";
import { useStore } from "@/lib/store";
import { Badge, Button, PlatformBadge, ScoreBadge, cx } from "./ui";

export function PhonePreview({ hook, variant }: { hook: string; variant?: string }) {
  return (
    <div className="relative flex aspect-[9/16] w-24 max-w-full shrink-0 items-end justify-center rounded-xl border-2 border-ink bg-gradient-to-b from-accent-soft to-surface p-2">
      {variant && <span className="absolute left-1.5 top-1.5 rounded bg-surface px-1 font-mono text-[10px]">{variant}</span>}
      {hook && <span className="rounded-sm bg-ink px-1 py-0.5 text-center text-[9px] font-extrabold leading-tight text-paper">{hook}</span>}
    </div>
  );
}

export function ClipCard({ clip }: { clip: Clip }) {
  const { setClipStatus, notify } = useStore();
  const platforms = Object.keys(clip.copy) as Platform[];
  return (
    <article
      className={cx(
        "flex min-w-0 flex-col gap-4 rounded-md border bg-surface p-4 sm:flex-row",
        clip.status === "approved" && "border-free/40",
        clip.status === "pending" && "border-gate/40",
        clip.status === "rejected" && "border-line opacity-70",
      )}
    >
      <div className="flex gap-2">
        {(clip.variants.length ? clip.variants : [""]).map((v) => (
          <PhonePreview key={v || "none"} hook={clip.hook} variant={v || undefined} />
        ))}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <ScoreBadge score={clip.score} />
          <h3 className="font-semibold">{clip.title}</h3>
          {clip.status === "approved" && <Badge tone="free">Approved</Badge>}
          {clip.status === "pending" && <Badge tone="gate">Needs approval</Badge>}
          {clip.status === "rejected" && <Badge>Rejected</Badge>}
        </div>
        <div className="tnum font-mono text-xs text-muted">
          {clip.start} → {clip.end} · {clip.seconds}s · {clip.variants.length || "no"} variant{clip.variants.length === 1 ? "" : "s"}
        </div>
        <p className="text-sm text-muted">
          <span className="font-medium text-ink">Why: </span>
          {clip.reason}
        </p>
        {platforms.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm">
            {platforms.map((p) => (
              <li key={p} className="flex items-start gap-2">
                <PlatformBadge platform={p} />
                <span className="min-w-0">{clip.copy[p]}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-auto flex flex-wrap gap-2 pt-1">
          {clip.status !== "approved" && (
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                setClipStatus(clip.id, "approved");
                notify(`Approved "${clip.title}"`);
              }}
            >
              <Check size={14} /> Approve
            </Button>
          )}
          <Button size="sm" onClick={() => notify("Timeline editor opens here (next step)")}>
            <Pencil size={14} /> Edit
          </Button>
          {clip.status !== "rejected" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setClipStatus(clip.id, "rejected");
                notify(`Rejected "${clip.title}"`);
              }}
            >
              <X size={14} /> Reject
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}
