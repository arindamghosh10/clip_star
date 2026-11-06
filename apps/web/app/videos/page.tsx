"use client";

import Link from "next/link";
import { useState } from "react";
import { CloudUpload, HardDrive, Link2 } from "lucide-react";
import { Badge, Button, Card, PageHeader, Progress } from "@/components/ui";
import { STAGES, VIDEOS, type VideoStatus } from "@/lib/data";
import { useStore } from "@/lib/store";

const statusLabel: Record<VideoStatus, { label: string; tone: "accent" | "gate" | "free" | "neutral" }> = {
  processing: { label: "Processing", tone: "accent" },
  review: { label: "Needs review", tone: "gate" },
  publishing: { label: "Publishing", tone: "free" },
  done: { label: "Done", tone: "neutral" },
};

export default function Videos() {
  const { notify } = useStore();
  const [drag, setDrag] = useState(false);

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
          notify(`Upload started: ${e.dataTransfer.files[0]?.name ?? "video"} (prototype)`);
        }}
        className={`flex flex-col items-center gap-3 rounded-md border-2 border-dashed p-8 text-center transition-colors ${drag ? "border-accent bg-accent-soft" : "border-line bg-surface"}`}
      >
        <CloudUpload size={28} className="text-accent" />
        <div>
          <p className="font-semibold">Drop a video file here</p>
          <p className="text-sm text-muted">MP4, MOV or MKV, up to 4 hours. The original is stored once and every stage reads from it.</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button variant="primary" onClick={() => notify("File picker would open here (prototype)")}>
            <CloudUpload size={16} /> Choose file
          </Button>
          <Button onClick={() => notify("Google Drive import (prototype)")}>
            <HardDrive size={16} /> From Google Drive
          </Button>
          <Button onClick={() => notify("Dropbox import (prototype)")}>
            <HardDrive size={16} /> From Dropbox
          </Button>
          <Button onClick={() => notify("Paste a direct file or stream VOD link (prototype)")}>
            <Link2 size={16} /> Paste a link
          </Button>
        </div>
        <p className="max-w-xl text-xs text-muted">
          New YouTube uploads on your connected channels show up below as a reminder. YouTube doesn&apos;t let apps download the original file, so upload it here to clip it.
        </p>
      </div>

      <Card title="All videos" padded={false}>
        <ul className="divide-y divide-line">
          {VIDEOS.map((v) => {
            const st = statusLabel[v.status];
            const stageIdx = STAGES.findIndex((s) => s.id === v.stage);
            return (
              <li key={v.id}>
                <Link href={`/videos/${v.id}`} className="grid gap-3 px-5 py-4 hover:bg-paper sm:grid-cols-[minmax(0,1fr)_160px_120px] sm:items-center">
                  <div className="min-w-0">
                    <div className="font-semibold">{v.title}</div>
                    <div className="tnum font-mono text-xs text-muted">
                      {v.file} · {v.duration} · uploaded {v.uploaded}
                    </div>
                  </div>
                  <div className="flex flex-col gap-1">
                    <span className="font-mono text-xs text-muted">
                      Stage {String(stageIdx + 1).padStart(2, "0")} · {STAGES[stageIdx].name}
                    </span>
                    <Progress value={v.status === "processing" ? v.progress : 100} />
                  </div>
                  <div className="flex items-center gap-2 sm:justify-end">
                    <Badge tone={st.tone}>{st.label}</Badge>
                    {v.clips > 0 && <span className="font-mono text-xs text-muted">{v.clips} clips</span>}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      </Card>
    </>
  );
}
