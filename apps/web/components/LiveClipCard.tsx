"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, Check, Pencil, RefreshCw, RotateCcw, X } from "lucide-react";
import { api, clipCoverUrl, clipMediaUrl, fmtDuration, type ApiClip } from "@/lib/api";
import { useStore } from "@/lib/store";
import { Badge, Button, ScoreBadge, cx } from "./ui";

const layoutLabel = { crop: "Follows the speaker", fit: "Full frame on blur", scale: "Already vertical" } as const;

export function LiveClipCard({ clip, onChange, showVideoLink = false }: { clip: ApiClip; onChange: (c: ApiClip) => void; showVideoLink?: boolean }) {
  const { notify } = useStore();
  const [variant, setVariant] = useState(clip.variants[0]?.id ?? "A");
  const [busy, setBusy] = useState(false);
  const render = clip.meta.renders?.[variant];
  const error = clip.meta.render_errors?.[variant];
  const dur = clip.end_s - clip.start_s;

  async function act(fn: () => Promise<ApiClip | unknown>, ok: string) {
    setBusy(true);
    try {
      const r = await fn();
      if (r && typeof r === "object" && "id" in r && "variants" in r) onChange(r as ApiClip);
      notify(ok);
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      className={cx(
        "flex min-w-0 flex-col gap-4 rounded-md border bg-surface p-4 sm:flex-row",
        clip.status === "approved" && "border-free/40",
        clip.status === "pending" && "border-gate/40",
        clip.status === "rejected" && "border-line opacity-70",
      )}
    >
      <div className="flex shrink-0 flex-col gap-2">
        <div className="relative aspect-[9/16] w-40 max-w-full overflow-hidden rounded-lg border border-line bg-ink/90">
          {render ? (
            <video
              key={`${clip.id}-${variant}-${render.key}`}
              controls
              preload="none"
              playsInline
              poster={clipCoverUrl(clip.id, variant, render.key)}
              src={clipMediaUrl(clip.id, variant, render.key)}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full items-center justify-center p-3 text-center text-xs text-paper/80">{error ? "Render failed" : clip.status === "rejected" ? "Not rendered" : "Rendering…"}</div>
          )}
        </div>
        {clip.variants.length > 1 && (
          <div className="flex gap-1" role="radiogroup" aria-label="Variant">
            {clip.variants.map((v) => (
              <button
                key={v.id}
                role="radio"
                aria-checked={variant === v.id}
                onClick={() => setVariant(v.id)}
                className={cx("flex-1 rounded border px-2 py-1 text-xs font-medium", variant === v.id ? "border-accent bg-accent-soft text-accent" : "border-line text-muted")}
              >
                {v.id} · {v.caption_style === "bold-pop" ? "Bold" : "Clean"}
              </button>
            ))}
          </div>
        )}
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
          {fmtDuration(clip.start_s)} → {fmtDuration(clip.end_s)} · {dur.toFixed(0)}s · picked by {clip.engine}
          {render ? ` · ${layoutLabel[render.layout.mode]}` : ""}
          {showVideoLink && (
            <>
              {" · "}
              <Link href={`/videos/${clip.video_id}`} className="underline">
                source video
              </Link>
            </>
          )}
        </div>
        <p className="text-sm text-muted">
          <span className="font-medium text-ink">Why: </span>
          {clip.reason}
        </p>
        <p className="text-sm">
          <span className="font-medium">On-screen hook ({variant}): </span>
          {clip.variants.find((v) => v.id === variant)?.hook || "none"}
        </p>
        {Object.entries(clip.meta.preflight ?? {}).some(([, p]) => p && !p.ok) && (
          <p className="flex items-start gap-2 rounded bg-paid-soft p-2 text-sm text-paid">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            Doesn&apos;t fit:{" "}
            {Object.entries(clip.meta.preflight ?? {})
              .filter(([, p]) => p && !p.ok)
              .map(([k]) => k)
              .join(", ")}
            . Open the editor to fix.
          </p>
        )}
        {error && (
          <p className="flex items-start gap-2 rounded bg-rec/10 p-2 text-sm text-rec">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {error}
          </p>
        )}
        <div className="mt-auto flex flex-wrap gap-2 pt-1">
          {clip.status !== "approved" && (
            <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => api.updateClip(clip.id, { status: "approved" }), `Approved "${clip.title}"`)}>
              <Check size={14} /> Approve
            </Button>
          )}
          <Link href={`/clips/${clip.id}`}>
            <Button size="sm">
              <Pencil size={14} /> Edit
            </Button>
          </Link>
          {clip.status === "rejected" ? (
            <Button size="sm" disabled={busy} onClick={() => act(() => api.updateClip(clip.id, { status: "pending" }), "Restored")}>
              <RotateCcw size={14} /> Restore
            </Button>
          ) : (
            <>
              <Button size="sm" disabled={busy} onClick={() => act(() => api.rerenderClip(clip.id), "Re-render queued")}>
                <RefreshCw size={14} /> Re-render
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api.updateClip(clip.id, { status: "rejected" }), `Rejected "${clip.title}"`)}>
                <X size={14} /> Reject
              </Button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}
