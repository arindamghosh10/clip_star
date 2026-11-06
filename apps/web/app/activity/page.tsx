"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, RotateCcw, Square } from "lucide-react";
import { Badge, Button, Card, Dot, EmptyNote, PageHeader, Progress, Tabs } from "@/components/ui";
import { api, fmtTime, type ApiJob, type JobStatus } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const tone: Record<JobStatus, "accent" | "free" | "rec" | "neutral"> = {
  queued: "neutral",
  running: "accent",
  succeeded: "free",
  failed: "rec",
  cancelled: "neutral",
};

function jobLabel(j: ApiJob) {
  if (j.kind === "pipeline.stage" && j.payload.stage) return `Stage: ${j.payload.stage}`;
  return j.kind;
}

export default function Activity() {
  const [tab, setTab] = useState<JobStatus | "all">("all");
  const health = usePoll(api.health, { intervalMs: 5000 });
  const jobs = usePoll(() => api.jobs(tab === "all" ? {} : { status: tab }), { intervalMs: 2500, deps: [tab] });
  const h = health.data;

  return (
    <>
      <PageHeader
        eyebrow="System"
        title="Activity"
        description="Every piece of work the system does: what's running, what's waiting, and what failed and why. Failed work can be retried here."
      />

      <Card title="System health">
        {health.error ? (
          <p role="alert" className="flex items-start gap-2 text-sm text-rec">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {health.error}
          </p>
        ) : !h ? (
          <p className="text-sm text-muted">Checking…</p>
        ) : (
          <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <Check ok={h.database} label="Database" />
            <Check ok={h.workers_online > 0} label={h.workers_online ? `${h.workers_online} worker${h.workers_online > 1 ? "s" : ""} online` : "No worker running"} hint={h.workers_online ? undefined : "Start one: python -m clipstar.worker"} />
            <Check ok={h.ffmpeg && h.ffprobe} label="FFmpeg" />
            <Check ok={h.storage_writable && h.storage_free_gb > 5} warn={h.storage_writable && h.storage_free_gb <= 5} label={`Storage · ${h.storage_free_gb} GB free`} />
            <div className="text-muted">Waiting: {h.queued_jobs}</div>
            <div className={h.failed_jobs ? "text-rec" : "text-muted"}>Failed: {h.failed_jobs}</div>
          </div>
        )}
      </Card>

      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { id: "all", label: "All" },
          { id: "running", label: "Running" },
          { id: "queued", label: "Waiting" },
          { id: "failed", label: "Failed" },
          { id: "succeeded", label: "Done" },
        ]}
      />

      {jobs.error && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {jobs.error}
        </p>
      )}
      <Card padded={false}>
        {jobs.loading && !jobs.data ? (
          <p className="px-5 py-6 text-sm text-muted">Loading…</p>
        ) : !jobs.data?.length ? (
          <div className="p-5">
            <EmptyNote>Nothing here.</EmptyNote>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {jobs.data.map((j) => (
              <JobRow key={j.id} j={j} onChange={jobs.refresh} />
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function Check({ ok, warn, label, hint }: { ok: boolean; warn?: boolean; label: string; hint?: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-1.5">
        <Dot tone={ok ? "ok" : warn ? "warn" : "bad"} />
      </span>
      <span>
        {label}
        {hint && <span className="block font-mono text-xs text-muted">{hint}</span>}
      </span>
    </div>
  );
}

function JobRow({ j, onChange }: { j: ApiJob; onChange: () => void }) {
  const { notify } = useStore();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ApiJob | null>(null);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      try {
        setDetail(await api.job(j.id));
      } catch (e) {
        notify(e instanceof Error ? e.message : String(e));
      }
    }
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      notify(ok);
      onChange();
      if (open) setDetail(await api.job(j.id));
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const retryIn = j.status === "queued" && j.attempts > 0 ? Math.max(0, Math.round((new Date(j.run_after).getTime() - Date.now()) / 1000)) : null;

  return (
    <li className="px-5 py-3">
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <button onClick={toggle} className="flex min-w-0 items-start gap-2 text-left" aria-expanded={open}>
          {open ? <ChevronDown size={16} className="mt-0.5 shrink-0" /> : <ChevronRight size={16} className="mt-0.5 shrink-0" />}
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{jobLabel(j)}</span>
              <Badge tone={tone[j.status]}>{j.status}</Badge>
              {j.attempts > 1 && <span className="font-mono text-xs text-muted">attempt {j.attempts} of {j.max_attempts}</span>}
              {retryIn !== null && <span className="font-mono text-xs text-paid">retrying in {retryIn}s</span>}
            </span>
            <span className="block font-mono text-xs text-muted">
              {fmtTime(j.created_at)}
              {j.video_id && (
                <>
                  {" · "}
                  <Link href={`/videos/${j.video_id}`} className="underline" onClick={(e) => e.stopPropagation()}>
                    video
                  </Link>
                </>
              )}
            </span>
            {j.last_error && (j.status === "failed" || retryIn !== null) && <span className="mt-1 block text-sm text-rec">{j.last_error}</span>}
          </span>
        </button>
        <div className="flex items-center gap-2">
          {j.status === "running" && <Progress value={j.progress} className="w-28" />}
          {(j.status === "failed" || j.status === "cancelled") && (
            <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => api.retryJob(j.id), "Retrying")}>
              <RotateCcw size={14} /> Retry
            </Button>
          )}
          {(j.status === "queued" || j.status === "running") && (
            <Button size="sm" disabled={busy} onClick={() => act(() => api.cancelJob(j.id), "Cancelled")}>
              <Square size={12} /> Cancel
            </Button>
          )}
        </div>
      </div>
      {open && (
        <ol className="ml-6 mt-3 flex flex-col gap-1 border-l border-line pl-4 text-sm">
          {!detail ? (
            <li className="text-muted">Loading…</li>
          ) : (
            detail.events
              ?.filter((e) => e.type !== "traceback")
              .map((e) => (
                <li key={e.id} className="grid gap-x-2 sm:grid-cols-[140px_110px_minmax(0,1fr)]">
                  <span className="font-mono text-xs text-muted">{fmtTime(e.at)}</span>
                  <span className="font-mono text-xs">{e.type}</span>
                  <span className="min-w-0 break-words">{e.message}</span>
                </li>
              ))
          )}
        </ol>
      )}
    </li>
  );
}
