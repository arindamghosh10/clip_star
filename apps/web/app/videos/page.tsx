"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { AlertTriangle, CloudUpload, FileText, Link2, X } from "lucide-react";
import { Badge, Button, Card, EmptyNote, PageHeader, Progress } from "@/components/ui";
import { STAGES } from "@/lib/data";
import { api, fmtBytes, fmtDuration, fmtTime, uploadVideo, type ApiVideo, type VideoStatus } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const statusBadge: Record<VideoStatus, { label: string; tone: "accent" | "gate" | "free" | "neutral" | "rec" }> = {
  queued: { label: "Queued", tone: "neutral" },
  processing: { label: "Processing", tone: "accent" },
  ready: { label: "Ready", tone: "free" },
  failed: { label: "Needs attention", tone: "rec" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const VIDEO_TYPES = ".mp4,.mov,.mkv,.webm,.m4v,.avi";

export default function Videos() {
  const { notify } = useStore();
  const { data: videos, error, loading, refresh } = usePoll(api.videos, {
    active: (d) => !d || d.some((v) => v.status === "queued" || v.status === "processing"),
  });
  const [drag, setDrag] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [captions, setCaptions] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [upload, setUpload] = useState<{ pct: number; abort: () => void } | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const capInput = useRef<HTMLInputElement>(null);

  function pick(f: File | undefined) {
    if (!f) return;
    setUploadError(null);
    setFile(f);
    setTitle(f.name.replace(/\.[^.]+$/, ""));
  }

  async function start() {
    if (!file) return;
    setUploadError(null);
    const u = uploadVideo(file, { title: title.trim() || undefined, captions, onProgress: (pct) => setUpload((s) => (s ? { ...s, pct } : s)) });
    setUpload({ pct: 0, abort: u.abort });
    try {
      const v = await u.promise;
      notify(`Uploaded "${v.title}". Processing started.`);
      setFile(null);
      setCaptions(null);
      setTitle("");
      refresh();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setUpload(null);
    }
  }

  return (
    <>
      <PageHeader eyebrow="Stage 01 · Ingest" title="Videos" description="Add a long video and clip_star takes it through the pipeline." />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          pick(e.dataTransfer.files[0]);
        }}
        className={`flex flex-col gap-4 rounded-md border-2 border-dashed p-6 transition-colors ${drag ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}
      >
        <input ref={fileInput} id="video-file" type="file" accept={VIDEO_TYPES} className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
        <input ref={capInput} id="captions-file" type="file" accept=".srt,.vtt" className="hidden" onChange={(e) => setCaptions(e.target.files?.[0] ?? null)} />

        {!file ? (
          <div className="flex flex-col items-center gap-3 text-center">
            <CloudUpload size={28} className="text-accent" />
            <div>
              <p className="font-semibold">Drop a video file here</p>
              <p className="text-sm text-muted">MP4, MOV, MKV, WebM, M4V or AVI. The original is stored once and every stage reads from it.</p>
            </div>
            <Button variant="primary" onClick={() => fileInput.current?.click()}>
              <CloudUpload size={16} /> Choose file
            </Button>
            <FromLink onDone={() => refresh()} />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate font-semibold">{file.name}</div>
                <div className="font-mono text-xs text-muted">{fmtBytes(file.size)}</div>
              </div>
              {!upload && (
                <Button variant="ghost" size="sm" onClick={() => setFile(null)}>
                  <X size={14} /> Remove
                </Button>
              )}
            </div>
            <label htmlFor="video-title" className="flex flex-col gap-1 text-sm">
              <span className="text-muted">Title</span>
              <input id="video-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} disabled={!!upload} className="rounded border border-line bg-paper px-3 py-2" />
            </label>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Button size="sm" onClick={() => capInput.current?.click()} disabled={!!upload}>
                <FileText size={14} /> {captions ? "Change captions file" : "Add captions file (optional)"}
              </Button>
              {captions && (
                <span className="flex items-center gap-1 text-muted">
                  {captions.name}
                  <button className="rounded p-0.5 hover:bg-paper" onClick={() => setCaptions(null)} aria-label="Remove captions file" disabled={!!upload}>
                    <X size={12} />
                  </button>
                </span>
              )}
              <span className="text-xs text-muted">An .srt or .vtt file gives exact words and skips speech recognition.</span>
            </div>
            {upload ? (
              <div className="flex items-center gap-3">
                <Progress value={upload.pct} className="flex-1" />
                <span className="tnum w-12 text-right font-mono text-xs">{upload.pct}%</span>
                <Button size="sm" variant="ghost" onClick={upload.abort}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button variant="primary" className="self-start" onClick={start}>
                Upload and process
              </Button>
            )}
          </div>
        )}
        {uploadError && (
          <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {uploadError}
          </p>
        )}
      </div>

      <Card title="All videos" padded={false}>
        {error && (
          <p role="alert" className="flex items-start gap-2 border-b border-line bg-rec/10 px-5 py-3 text-sm text-rec">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {error}
          </p>
        )}
        {loading && !videos ? (
          <p className="px-5 py-6 text-sm text-muted">Loading…</p>
        ) : !videos?.length ? (
          <div className="p-5">
            <EmptyNote>No videos yet. Upload one above to start.</EmptyNote>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {videos.map((v) => (
              <VideoRow key={v.id} v={v} />
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function VideoRow({ v }: { v: ApiVideo }) {
  const st = statusBadge[v.status];
  const idx = STAGES.findIndex((s) => s.id === v.stage);
  const running = v.status === "processing" || v.status === "queued";
  return (
    <li>
      <Link href={`/videos/${v.id}`} className="grid gap-3 px-5 py-4 hover:bg-paper sm:grid-cols-[minmax(0,1fr)_180px_150px] sm:items-center">
        <div className="min-w-0">
          <div className="truncate font-semibold">{v.title}</div>
          <div className="tnum truncate font-mono text-xs text-muted">
            {v.source_filename} · {fmtDuration(v.duration_s)} · {fmtBytes(v.size_bytes)} · {fmtTime(v.created_at)}
          </div>
          {v.status === "failed" && v.error && <div className="mt-1 truncate text-xs text-rec">{v.error}</div>}
        </div>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-xs text-muted">
            Stage {String(idx + 1).padStart(2, "0")} · {STAGES[idx]?.name}
          </span>
          <Progress value={running ? v.progress : v.status === "ready" ? 100 : v.progress} />
        </div>
        <div className="flex items-center gap-2 sm:justify-end">
          <Badge tone={st.tone}>{st.label}</Badge>
        </div>
      </Link>
    </li>
  );
}


function FromLink({ onDone }: { onDone: () => void }) {
  const { notify } = useStore();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.importVideo(url.trim());
      setUrl("");
      notify("Downloading the video. Processing starts when it's in.");
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={go} className="flex w-full max-w-xl flex-col gap-1.5">
      <span className="text-xs text-muted">or add from a link: Google Drive, Dropbox, or a direct link to the file</span>
      <span className="flex gap-2">
        <input type="url" aria-label="Video link" placeholder="https://drive.google.com/file/d/…" value={url} onChange={(e) => setUrl(e.target.value)} className="min-w-0 flex-1 rounded border border-line bg-paper px-3 py-2 text-sm" />
        <Button type="submit" disabled={!url.trim() || busy}>
          <Link2 size={14} /> {busy ? "Adding…" : "Add"}
        </Button>
      </span>
      {error && <span role="alert" className="text-left text-xs text-rec">{error}</span>}
    </form>
  );
}
