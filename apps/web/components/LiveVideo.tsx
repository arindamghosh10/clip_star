"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ChevronLeft, RotateCcw, Square, Trash2 } from "lucide-react";
import { api, fmtBytes, fmtDuration, fmtTime, type Analysis, type ApiVideo, type Transcript } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";
import { LiveClipCard } from "./LiveClipCard";
import { PipelineRail } from "./PipelineRail";
import { Badge, Button, Card, EmptyNote, PageHeader, Progress } from "./ui";

export function LiveVideo({ id }: { id: string }) {
  const router = useRouter();
  const { notify } = useStore();
  const { data: v, error, refresh } = usePoll(() => api.video(id), {
    intervalMs: 2000,
    active: (d) => !d || d.status === "queued" || d.status === "processing",
    deps: [id],
  });
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      notify(ok);
      await refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !v) {
    return (
      <>
        <Back />
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-4 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {error}
        </p>
      </>
    );
  }
  if (!v) return <p className="text-sm text-muted">Loading…</p>;

  const running = v.status === "queued" || v.status === "processing";
  const u = v.meta.understand;
  const p = v.meta.probe;

  return (
    <>
      <Back />
      <PageHeader
        eyebrow={`${v.source_filename} · ${fmtDuration(v.duration_s)} · ${fmtBytes(v.size_bytes)}`}
        title={v.title}
        description={`Uploaded ${fmtTime(v.created_at)}${p ? ` · ${p.width}×${p.height} · ${p.fps} fps${p.has_audio ? "" : " · no audio"}` : ""}`}
        actions={
          <>
            {v.status === "failed" || v.status === "cancelled" ? (
              <Button variant="primary" disabled={busy} onClick={() => act(() => api.retryVideo(v.id), "Retrying")}>
                <RotateCcw size={16} /> Retry
              </Button>
            ) : null}
            {v.status === "ready" && <ExternalClipButtons videoId={v.id} />}
            {running && (
              <Button disabled={busy} onClick={() => act(() => api.cancelVideo(v.id), "Processing cancelled")}>
                <Square size={14} /> Cancel
              </Button>
            )}
            {confirmDelete ? (
              <>
                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await api.deleteVideo(v.id);
                      router.push("/videos");
                    }, "Video deleted")
                  }
                >
                  Delete for good
                </Button>
                <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                  Keep
                </Button>
              </>
            ) : (
              <Button variant="ghost" onClick={() => setConfirmDelete(true)}>
                <Trash2 size={16} /> Delete
              </Button>
            )}
          </>
        }
      />

      {v.status === "failed" && v.error && (
        <p role="alert" className="flex items-start gap-2 rounded border border-rec/30 bg-rec/10 p-4 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>
            <b>Stopped at {v.stage}:</b> {v.error}{" "}
            <Link href="/activity" className="underline">
              See details in Activity
            </Link>
          </span>
        </p>
      )}

      <Card
        title="Pipeline progress"
        actions={<Badge tone={v.status === "ready" ? "free" : v.status === "failed" ? "rec" : running ? "accent" : "neutral"}>{v.status === "ready" ? "Clips ready" : v.status}</Badge>}
      >
        <PipelineRail current={v.status === "ready" ? undefined : v.stage} doneThrough={v.status === "ready" ? "package" : undefined} />
        {running && (
          <div className="mt-4 flex items-center gap-3 text-sm">
            <span className="text-muted">{v.status === "queued" ? "Waiting for a worker…" : `Running ${v.stage}…`}</span>
            <Progress value={v.progress} className="max-w-xs flex-1" />
            <span className="tnum font-mono text-xs">{v.progress}%</span>
          </div>
        )}
        {v.status === "ready" && (
          <p className="mt-3 text-sm text-muted">
            Clips, captions and post text are ready to review. Publishing arrives in the next build phase.
          </p>
        )}
      </Card>

      {u && <Understood v={v} />}
      <VideoClips v={v} />
    </>
  );
}

function VideoClips({ v }: { v: ApiVideo }) {
  const clips = usePoll(() => api.clips({ video_id: v.id }), {
    intervalMs: 3000,
    deps: [v.id, v.status, v.stage],
    active: (d) => v.status === "processing" || v.status === "queued" || !!d?.some((c) => c.status !== "rejected" && c.variants.some((x) => !c.meta.renders?.[x.id] && !c.meta.render_errors?.[x.id])),
  });
  const notes = v.meta.moments?.notes ?? [];
  const reached = ["moments", "edit"].includes(v.stage) || v.status === "ready";
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Stages 03–04 · Moments and clips</h2>
        {v.meta.moments && <span className="text-sm text-muted">Picked by {v.meta.moments.engine} · sorted by score</span>}
      </div>
      {notes.map((n) => (
        <p key={n} className="rounded border border-paid/30 bg-paid-soft px-3 py-2 text-sm text-paid">
          {n}
        </p>
      ))}
      {clips.error && <p className="text-sm text-rec">{clips.error}</p>}
      {clips.data?.length ? (
        clips.data.map((c) => <LiveClipCard key={c.id} clip={c} onChange={(n) => clips.setData((d) => d?.map((x) => (x.id === n.id ? n : x)))} />)
      ) : (
        <EmptyNote>
          {!reached
            ? "Clips appear here after the Find moments stage."
            : v.status === "ready"
              ? "No moments fit the clip length limits. Try a longer video, or change the clip length in Settings."
              : "Finding moments…"}
        </EmptyNote>
      )}
    </section>
  );
}

function Back() {
  return (
    <Link href="/videos" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
      <ChevronLeft size={16} /> Videos
    </Link>
  );
}

function Understood({ v }: { v: ApiVideo }) {
  const u = v.meta.understand!;
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([api.analysis(v.id), api.transcript(v.id)])
      .then(([a, t]) => {
        if (live) {
          setAnalysis(a);
          setTranscript(t);
        }
      })
      .catch((e) => live && setErr(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [v.id, v.updated_at]);

  const values = analysis?.energy.values ?? [];
  const bars = 120;
  const step = Math.max(1, Math.ceil(values.length / bars));
  const buckets = Array.from({ length: Math.ceil(values.length / step) }, (_, i) => Math.max(...values.slice(i * step, (i + 1) * step)));
  const peaks = new Set((analysis?.energy.peaks ?? []).map((p) => Math.floor(p / (analysis!.energy.window_s * step))));

  return (
    <Card title="Stage 02 · What the system understood">
      <div className="flex flex-col gap-4">
        {err && <p className="text-sm text-rec">{err}</p>}
        {buckets.length > 0 && (
          <>
            <div className="flex h-16 items-end gap-[2px]" aria-label="Audio energy across the video">
              {buckets.map((b, i) => (
                <span key={i} className={`flex-1 rounded-sm ${peaks.has(i) ? "bg-rec" : "bg-line"}`} style={{ height: `${Math.max(4, b * 100)}%` }} />
              ))}
            </div>
            <div className="flex justify-between font-mono text-[11px] text-muted">
              <span>00:00:00</span>
              <span>{fmtDuration(v.duration_s)}</span>
            </div>
          </>
        )}
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Fact k="Words" v={u.words.toLocaleString("en-US")} />
          <Fact k="Scenes" v={String(u.scenes)} />
          <Fact k="High-energy moments" v={String(u.energy_peaks)} />
          <Fact k="Transcript" v={`${u.transcript_engine}${u.language ? ` · ${u.language}` : ""}`} />
        </dl>
        {u.notes.map((n) => (
          <p key={n} className="text-sm text-muted">
            {n}
          </p>
        ))}
        {transcript && transcript.segments.length > 0 && (
          <details className="rounded border border-line">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
              Transcript ({transcript.segments.length} lines) ·{" "}
              <Link href={`/videos/${v.id}/transcript`} className="text-accent">Edit</Link>
            </summary>
            <ol className="max-h-80 overflow-y-auto border-t border-line text-sm">
              {transcript.segments.map((s, i) => (
                <li key={i} className="grid grid-cols-[72px_minmax(0,1fr)] gap-2 border-b border-line px-3 py-1.5 last:border-0">
                  <span className="tnum font-mono text-xs text-muted">{fmtDuration(s.start)}</span>
                  <span>{s.text}</span>
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
    </Card>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="min-w-0 rounded border border-line bg-paper p-3">
      <dt className="text-xs text-muted">{k}</dt>
      <dd className="truncate text-lg font-semibold">{v}</dd>
    </div>
  );
}


/** "Also clip with Klap / Vizard": shown only for services set up on the server. */
function ExternalClipButtons({ videoId }: { videoId: string }) {
  const { notify } = useStore();
  const [vendors, setVendors] = useState<{ id: string; name: string; configured: boolean }[]>([]);
  useEffect(() => {
    api.externalClippers().then((v) => setVendors(v.filter((x) => x.configured))).catch(() => setVendors([]));
  }, []);
  return (
    <>
      {vendors.map((x) => (
        <Button key={x.id} onClick={() => api.externalClips(videoId, x.id).then(() => notify(`Sent to ${x.name}. Its clips appear in Clips for review when ready.`)).catch((e) => notify(e instanceof Error ? e.message : String(e)))}>
          Also clip with {x.name}
        </Button>
      ))}
    </>
  );
}
