"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Check, ChevronLeft, Minus, Plus, X } from "lucide-react";
import { Badge, Button, Card, PageHeader, ScoreBadge, Tabs, cx } from "@/components/ui";
import {
  PLATFORM_RULES,
  api,
  clipCoverUrl,
  clipMediaUrl,
  composeCopy,
  fmtDuration,
  proxyUrl,
  type ApiClip,
  type ApiJob,
  type ClipVariant,
  type PlatformCopy,
  type PlatformId,
  type Transcript,
} from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const fmt = (s: number) => `${fmtDuration(s)}.${Math.floor((s % 1) * 10)}`;

export default function ClipEditor() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useStore();
  const clip = usePoll(() => api.clip(id), { intervalMs: 3000, deps: [id], active: () => true });
  const c = clip.data;
  const jobs = usePoll(() => (c ? api.jobs({ video_id: c.video_id }) : Promise.resolve([] as ApiJob[])), { intervalMs: 3000, deps: [c?.video_id] });
  const rendering = (jobs.data ?? []).some((j) => j.kind === "clip.render" && (j.status === "queued" || j.status === "running") && j.payload.clip_id === id);

  if (clip.error && !c) {
    return (
      <>
        <BackLink />
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-4 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {clip.error}
        </p>
      </>
    );
  }
  if (!c) return <p className="text-sm text-muted">Loading…</p>;

  async function save(body: Parameters<typeof api.updateClip>[1], ok: string) {
    try {
      const n = await api.updateClip(id, body);
      clip.setData(n);
      notify(ok);
      jobs.refresh();
      return true;
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
      return false;
    }
  }

  return (
    <>
      <BackLink />
      <PageHeader
        eyebrow={`Clip editor · ${fmt(c.start_s)} → ${fmt(c.end_s)}`}
        title={c.title}
        actions={
          <>
            {c.status !== "approved" && (
              <Button variant="primary" onClick={() => save({ status: "approved" }, "Approved")}>
                <Check size={16} /> Approve
              </Button>
            )}
            {c.status !== "rejected" ? (
              <Button variant="ghost" onClick={() => save({ status: "rejected" }, "Rejected")}>
                <X size={16} /> Reject
              </Button>
            ) : (
              <Button onClick={() => save({ status: "pending" }, "Restored")}>Restore</Button>
            )}
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <ScoreBadge score={c.score} />
        <Badge tone={c.status === "approved" ? "free" : c.status === "rejected" ? "neutral" : "gate"}>{c.status === "pending" ? "Needs approval" : c.status}</Badge>
        {c.meta.auto_approved && <Badge tone="accent">Auto-approved</Badge>}
        {rendering && <Badge tone="accent">Re-rendering…</Badge>}
        <span className="text-muted">{c.reason}</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Rendered clip={c} rendering={rendering} onChanged={() => clip.refresh()} />
        <Trim clip={c} onSave={save} />
      </div>
      <Variants clip={c} onSave={save} />
      <CopyEditor clip={c} onSave={save} />
      <FixWord clip={c} onDone={() => (clip.refresh(), jobs.refresh())} />
    </>
  );
}

function BackLink() {
  return (
    <Link href="/clips" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
      <ChevronLeft size={16} /> Clips
    </Link>
  );
}

type Save = (body: Parameters<typeof api.updateClip>[1], ok: string) => Promise<boolean>;

function Rendered({ clip, rendering, onChanged }: { clip: ApiClip; rendering: boolean; onChanged: () => void }) {
  const [variant, setVariant] = useState(clip.variants[0]?.id ?? "A");
  const [coverKey, setCoverKey] = useState("");
  const vid = useRef<HTMLVideoElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const { notify } = useStore();
  const r = clip.meta.renders?.[variant];
  const custom = !!clip.meta.custom_covers?.[variant];
  const posterKey = `${r?.key ?? ""}${clip.meta.custom_covers?.[variant] ?? ""}${coverKey}`;
  async function cover(p: Promise<{ key: string }>, ok: string) {
    try {
      const res = await p;
      setCoverKey(res.key);
      notify(ok);
      onChanged();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <Card title="Rendered clip">
      <div className="flex flex-col items-center gap-3">
        <div className="relative aspect-[9/16] w-56 max-w-full overflow-hidden rounded-lg border border-line bg-ink/90">
          {r ? (
            <video ref={vid} key={r.key} controls playsInline preload="metadata" poster={clipCoverUrl(clip.id, variant, posterKey)} src={clipMediaUrl(clip.id, variant, r.key)} className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full items-center justify-center p-3 text-center text-xs text-paper/80">{clip.meta.render_errors?.[variant] ?? "Not rendered yet"}</div>
          )}
          {rendering && <div className="absolute inset-x-0 top-0 bg-accent px-2 py-1 text-center text-xs text-surface">Updating with your changes…</div>}
        </div>
        {r && (
          <div className="flex w-full flex-col items-center gap-1.5 text-xs">
            <span className="text-muted">Cover: {custom ? "your own" : "automatic"}</span>
            <span className="flex flex-wrap justify-center gap-1">
              <Button size="sm" onClick={() => cover(api.coverFromFrame(clip.id, variant, vid.current?.currentTime ?? 1), "Cover set from this frame")} title="Pause the video where you want, then click">
                Use current frame
              </Button>
              <Button size="sm" onClick={() => file.current?.click()}>Upload image</Button>
              {custom && <Button size="sm" variant="ghost" onClick={() => cover(api.resetCover(clip.id, variant), "Back to the automatic cover")}>Reset</Button>}
            </span>
            <input
              ref={file}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) cover(api.uploadCover(clip.id, variant, f), "Cover uploaded");
              }}
            />
          </div>
        )}
        {clip.variants.length > 1 && (
          <div className="flex gap-1">
            {clip.variants.map((v) => (
              <button key={v.id} onClick={() => setVariant(v.id)} className={cx("rounded border px-3 py-1 text-xs font-medium", variant === v.id ? "border-accent bg-accent-soft text-accent" : "border-line text-muted")}>
                Variant {v.id}
              </button>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

function Trim({ clip, onSave }: { clip: ApiClip; onSave: Save }) {
  const [start, setStart] = useState(clip.start_s);
  const [end, setEnd] = useState(clip.end_s);
  const [tr, setTr] = useState<Transcript | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    setStart(clip.start_s);
    setEnd(clip.end_s);
  }, [clip.start_s, clip.end_s]);
  useEffect(() => {
    api.transcript(clip.video_id).then(setTr).catch(() => setTr(null));
  }, [clip.video_id]);

  const nearby = useMemo(() => (tr?.segments ?? []).filter((s) => s.end > clip.start_s - 30 && s.start < clip.end_s + 30), [tr, clip.start_s, clip.end_s]);
  const dur = end - start;
  const changed = Math.abs(start - clip.start_s) > 0.01 || Math.abs(end - clip.end_s) > 0.01;
  const invalid = dur < 3 || dur > 180;

  function preview() {
    const v = video.current;
    if (!v) return;
    v.currentTime = start;
    v.play().catch(() => undefined);
  }

  return (
    <Card title="Trim">
      <div className="flex flex-col gap-3">
        <video
          ref={video}
          src={proxyUrl(clip.video_id)}
          preload="metadata"
          controls
          playsInline
          className="aspect-video w-full rounded bg-ink"
          onLoadedMetadata={(e) => (e.currentTarget.currentTime = start)}
          onTimeUpdate={(e) => {
            if (e.currentTarget.currentTime >= end) e.currentTarget.pause();
          }}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Nudge label="Start" value={start} onChange={(v) => setStart(Math.max(0, Math.min(v, end - 3)))} />
          <Nudge label="End" value={end} onChange={(v) => setEnd(Math.max(start + 3, v))} />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className={cx("font-mono", invalid && "text-rec")}>{dur.toFixed(1)}s</span>
          <Button size="sm" onClick={preview}>
            Play selection
          </Button>
          <Button size="sm" variant="primary" disabled={!changed || invalid} onClick={() => onSave({ start_s: Math.round(start * 1000) / 1000, end_s: Math.round(end * 1000) / 1000 }, "Trim saved. Re-rendering.")}>
            Save trim
          </Button>
          {changed && (
            <Button size="sm" variant="ghost" onClick={() => (setStart(clip.start_s), setEnd(clip.end_s))}>
              Undo
            </Button>
          )}
        </div>
        {nearby.length > 0 && (
          <div className="max-h-56 overflow-y-auto rounded border border-line text-sm">
            {nearby.map((s, i) => {
              const inside = s.start >= start - 0.05 && s.end <= end + 0.05;
              return (
                <div key={i} className={cx("grid grid-cols-[64px_minmax(0,1fr)_auto] items-center gap-2 border-b border-line px-2 py-1.5 last:border-0", inside ? "bg-accent-soft" : "text-muted")}>
                  <span className="font-mono text-xs">{fmtDuration(s.start)}</span>
                  <span className="min-w-0">{s.text}</span>
                  <span className="flex gap-1">
                    <button className="rounded border border-line px-1.5 text-xs hover:border-accent" onClick={() => setStart(Math.max(0, s.start - 0.15))}>
                      Start
                    </button>
                    <button className="rounded border border-line px-1.5 text-xs hover:border-accent" onClick={() => setEnd(s.end + 0.4)}>
                      End
                    </button>
                  </span>
                </div>
              );
            })}
          </div>
        )}
        <p className="text-xs text-muted">Use Start/End on a sentence to cut on clean sentence boundaries.</p>
      </div>
    </Card>
  );
}

function Nudge({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 text-sm text-muted">{label}</span>
      <button aria-label={`${label} back half a second`} className="rounded border border-line p-1 hover:bg-paper" onClick={() => onChange(value - 0.5)}>
        <Minus size={14} />
      </button>
      <span className="tnum w-24 text-center font-mono text-sm">{fmt(value)}</span>
      <button aria-label={`${label} forward half a second`} className="rounded border border-line p-1 hover:bg-paper" onClick={() => onChange(value + 0.5)}>
        <Plus size={14} />
      </button>
    </div>
  );
}

function Variants({ clip, onSave }: { clip: ApiClip; onSave: Save }) {
  const [vs, setVs] = useState<ClipVariant[]>(clip.variants);
  const savedVs = JSON.stringify(clip.variants);
  // reset only when the saved value changes, not on every refresh (keeps unsaved typing)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setVs(clip.variants), [savedVs]);
  const changed = JSON.stringify(vs) !== JSON.stringify(clip.variants);
  const set = (i: number, patch: Partial<ClipVariant>) => setVs(vs.map((v, k) => (k === i ? { ...v, ...patch } : v)));
  return (
    <Card title="Hook and caption style">
      <div className="flex flex-col gap-3">
        {vs.map((v, i) => (
          <div key={v.id} className="grid items-end gap-3 sm:grid-cols-[80px_minmax(0,1fr)_180px_auto]">
            <span className="text-sm font-semibold">Variant {v.id}</span>
            <label htmlFor={`hook-${v.id}`} className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted">On-screen hook (first 3 seconds)</span>
              <input id={`hook-${v.id}`} value={v.hook} maxLength={60} onChange={(e) => set(i, { hook: e.target.value })} className="rounded border border-line bg-paper px-3 py-2 uppercase" />
            </label>
            <label htmlFor={`style-${v.id}`} className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted">Captions</span>
              <select id={`style-${v.id}`} value={v.caption_style} onChange={(e) => set(i, { caption_style: e.target.value })} className="rounded border border-line bg-surface px-2 py-2">
                <option value="bold-pop">Bold, word highlight</option>
                <option value="clean">Clean, boxed</option>
              </select>
            </label>
            {vs.length > 1 ? (
              <Button size="sm" variant="ghost" onClick={() => setVs(vs.filter((_, k) => k !== i))}>
                Remove
              </Button>
            ) : (
              <span />
            )}
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          {vs.length < 2 && (
            <Button size="sm" onClick={() => setVs([...vs, { id: vs[0]?.id === "A" ? "B" : "A", caption_style: "clean", hook: vs[0]?.hook ?? "" }])}>
              <Plus size={14} /> Add a variant
            </Button>
          )}
          <Button size="sm" variant="primary" disabled={!changed} onClick={() => onSave({ variants: vs }, "Saved. Re-rendering.")}>
            Save and re-render
          </Button>
        </div>
      </div>
    </Card>
  );
}

function CopyEditor({ clip, onSave }: { clip: ApiClip; onSave: Save }) {
  const platforms = (Object.keys(PLATFORM_RULES) as PlatformId[]).filter((p) => clip.copy[p] && typeof clip.copy[p] === "object");
  const [tab, setTab] = useState<PlatformId>(platforms[0] ?? "youtube");
  const [draft, setDraft] = useState<Partial<Record<PlatformId, PlatformCopy>>>(clip.copy);
  const savedCopy = JSON.stringify(clip.copy);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setDraft(clip.copy), [savedCopy]);
  if (!platforms.length) {
    return (
      <Card title="Post text">
        <p className="text-sm text-muted">Post text is written in the Package step, after the clip is rendered.</p>
      </Card>
    );
  }
  const rules = PLATFORM_RULES[tab];
  const c = draft[tab] ?? { title: "", caption: "", hashtags: [] };
  const total = composeCopy(c).length;
  const pre = clip.meta.preflight?.[tab];
  const changed = JSON.stringify(draft[tab]) !== JSON.stringify(clip.copy[tab]);
  const set = (patch: Partial<PlatformCopy>) => setDraft({ ...draft, [tab]: { ...c, ...patch } });
  const tooLong = total > rules.captionMax || c.hashtags.length > rules.hashtagsMax || (rules.needsTitle && c.title.length > rules.titleMax);

  return (
    <Card title="Post text per platform" actions={clip.meta.copy_engine && <span className="text-xs text-muted">Written by {clip.meta.copy_engine}{clip.meta.copy_edited ? " · edited by you" : ""}</span>}>
      <div className="flex flex-col gap-3">
        <Tabs
          value={tab}
          onChange={setTab}
          items={platforms.map((p) => ({ id: p, label: `${PLATFORM_RULES[p].label}${clip.meta.preflight?.[p]?.ok === false ? " ⚠" : ""}` }))}
        />
        {rules.needsTitle && (
          <label htmlFor="copy-title" className="flex flex-col gap-1 text-sm">
            <span className="flex justify-between text-xs text-muted">
              Title <span className={cx("font-mono", c.title.length > rules.titleMax && "text-rec")}>{c.title.length}/{rules.titleMax}</span>
            </span>
            <input id="copy-title" value={c.title} onChange={(e) => set({ title: e.target.value })} className="rounded border border-line bg-paper px-3 py-2" />
          </label>
        )}
        <label htmlFor="copy-caption" className="flex flex-col gap-1 text-sm">
          <span className="flex justify-between text-xs text-muted">
            Caption <span className={cx("font-mono", total > rules.captionMax && "text-rec")}>{total}/{rules.captionMax} with hashtags</span>
          </span>
          <textarea id="copy-caption" rows={5} value={c.caption} onChange={(e) => set({ caption: e.target.value })} className="rounded border border-line bg-paper px-3 py-2" />
        </label>
        <label htmlFor="copy-tags" className="flex flex-col gap-1 text-sm">
          <span className="flex justify-between text-xs text-muted">
            Hashtags, separated by spaces or commas
            <span className={cx("font-mono", c.hashtags.length > rules.hashtagsMax && "text-rec")}>
              {c.hashtags.length}/{rules.hashtagsMax}
            </span>
          </span>
          <input
            id="copy-tags"
            value={c.hashtags.map((h) => `#${h}`).join(" ")}
            onChange={(e) => set({ hashtags: e.target.value.split(/[\s,]+/).map((h) => h.replace(/^#+/, "")).filter(Boolean) })}
            className="rounded border border-line bg-paper px-3 py-2"
          />
        </label>
        {pre && !pre.ok && !changed && (
          <ul className="flex flex-col gap-1 rounded bg-rec/10 p-3 text-sm text-rec">
            {pre.problems.map((p) => (
              <li key={p} className="flex items-start gap-2">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {p}
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="primary" disabled={!changed} onClick={() => onSave({ copy: { [tab]: c } }, `${rules.label} text saved`)}>
            Save {rules.label} text
          </Button>
          {tooLong && <span className="text-xs text-rec">Over this platform&apos;s limits. You can save, but posting will be blocked until it fits.</span>}
        </div>
      </div>
    </Card>
  );
}

function FixWord({ clip, onDone }: { clip: ApiClip; onDone: () => void }) {
  const { notify } = useStore();
  const [find, setFind] = useState("");
  const [repl, setRepl] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      const r = await api.replaceInTranscript(clip.video_id, find, repl);
      notify(`Replaced ${r.replaced} time${r.replaced === 1 ? "" : "s"}; ${r.clips_changed} clip${r.clips_changed === 1 ? "" : "s"} re-rendering`);
      setFind("");
      setRepl("");
      onDone();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="Fix a word everywhere">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (find.trim()) go();
        }}
      >
        <label htmlFor="fix-find" className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Wrong word</span>
          <input id="fix-find" value={find} onChange={(e) => setFind(e.target.value)} maxLength={100} placeholder="e.g. clip star" className="rounded border border-line bg-paper px-3 py-2" />
        </label>
        <label htmlFor="fix-repl" className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Correct word</span>
          <input id="fix-repl" value={repl} onChange={(e) => setRepl(e.target.value)} maxLength={100} placeholder="e.g. clip_star" className="rounded border border-line bg-paper px-3 py-2" />
        </label>
        <Button type="submit" variant="primary" disabled={busy || !find.trim()}>
          Replace in transcript and captions
        </Button>
      </form>
      <p className="mt-2 text-xs text-muted">Fixes the whole video&apos;s transcript and every clip&apos;s captions; affected clips re-render.</p>
    </Card>
  );
}
