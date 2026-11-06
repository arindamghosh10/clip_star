"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { ClipCard } from "@/components/ClipCard";
import { LiveVideo } from "@/components/LiveVideo";
import { isUuid } from "@/lib/api";
import { PipelineRail } from "@/components/PipelineRail";
import { Card, EmptyNote, PageHeader, Progress } from "@/components/ui";
import { STAGES, VIDEOS } from "@/lib/data";
import { useStore } from "@/lib/store";

// Deterministic "energy" bars so the waveform looks the same on every render.
const ENERGY = Array.from({ length: 60 }, (_, i) => {
  const v = Math.abs(Math.sin(i * 1.7) * 0.5 + Math.sin(i * 0.37) * 0.35) + 0.15;
  return Math.min(1, v);
});
const HOT = new Set([14, 15, 21, 33, 34, 41, 47]);

export default function VideoPage() {
  const { id } = useParams<{ id: string }>();
  return isUuid(id) ? <LiveVideo id={id} /> : <SampleVideoDetail id={id} />;
}

function SampleVideoDetail({ id }: { id: string }) {
  const { clips } = useStore();
  const video = VIDEOS.find((v) => v.id === id);

  if (!video) {
    return (
      <>
        <PageHeader title="Video not found" />
        <Link href="/videos" className="text-accent">Back to videos</Link>
      </>
    );
  }

  const videoClips = clips.filter((c) => c.videoId === video.id).sort((a, b) => b.score - a.score);
  const stageIdx = STAGES.findIndex((s) => s.id === video.stage);

  return (
    <>
      <Link href="/videos" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ChevronLeft size={16} /> Videos
      </Link>
      <PageHeader eyebrow={`${video.file} · ${video.duration}`} title={video.title} description={`Uploaded ${video.uploaded}`} />

      <Card title="Pipeline progress" actions={<span className="font-mono text-xs text-muted">Stage {String(stageIdx + 1).padStart(2, "0")} of 09</span>}>
        <PipelineRail current={video.stage} />
        {video.status === "processing" && (
          <div className="mt-4 flex items-center gap-3 text-sm">
            <span className="text-muted">Finding moments…</span>
            <Progress value={video.progress} className="max-w-xs flex-1" />
            <span className="font-mono text-xs">{video.progress}%</span>
          </div>
        )}
      </Card>

      <Card title="Stage 02 · What the system understood">
        <div className="flex flex-col gap-4">
          <div className="flex h-16 items-end gap-[3px]" aria-label="Audio energy across the video">
            {ENERGY.map((v, i) => (
              <span key={i} className={`flex-1 rounded-sm ${HOT.has(i) ? "bg-rec" : "bg-line"}`} style={{ height: `${HOT.has(i) ? 95 : v * 70}%` }} />
            ))}
          </div>
          <div className="flex justify-between font-mono text-[11px] text-muted">
            <span>00:00</span>
            <span>{video.duration}</span>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Fact k="Speakers" v={String(video.speakers)} />
            <Fact k="Scenes" v={String(video.scenes)} />
            <Fact k="Words" v={video.words.toLocaleString("en-US")} />
            <Fact k="High-energy moments" v={String(HOT.size)} />
          </dl>
        </div>
      </Card>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Stages 03–05 · Moments, clips and copy</h2>
          <span className="text-sm text-muted">Sorted by score. Approve the ones to publish.</span>
        </div>
        {videoClips.length ? videoClips.map((c) => <ClipCard key={c.id} clip={c} />) : <EmptyNote>Clips appear here once moments are found.</EmptyNote>}
      </section>
    </>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded border border-line bg-paper p-3">
      <dt className="text-xs text-muted">{k}</dt>
      <dd className="tnum text-lg font-semibold">{v}</dd>
    </div>
  );
}
