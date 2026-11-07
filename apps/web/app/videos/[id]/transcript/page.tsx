"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, Play } from "lucide-react";
import { Badge, Button, Card, EmptyNote, PageHeader, cx } from "@/components/ui";
import { api, fmtDuration, proxyUrl, type Transcript } from "@/lib/api";
import { useAuth } from "@/components/Auth";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

export default function TranscriptEditor() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useStore();
  const { can } = useAuth();
  const editable = can("editor");
  const video = usePoll(() => api.video(id), { intervalMs: 60000, deps: [id] });
  const clips = usePoll(() => api.clips({ video_id: id }), { intervalMs: 60000, deps: [id] });
  const [tr, setTr] = useState<Transcript | null>(null);
  const [draft, setDraft] = useState<Record<number, string>>({});
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const player = useRef<HTMLVideoElement>(null);

  const load = () =>
    api
      .transcript(id)
      .then((t) => {
        setTr(t);
        setDraft({});
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // which clip (if any) each line belongs to, so people see what an edit will re-render
  const inClip = useMemo(() => {
    const m = new Map<number, string[]>();
    (tr?.segments ?? []).forEach((s, i) => {
      const names = (clips.data ?? []).filter((c) => s.start < c.end_s && s.end > c.start_s).map((c) => c.title);
      if (names.length) m.set(i, names);
    });
    return m;
  }, [tr, clips.data]);

  const changed = Object.entries(draft).filter(([i, t]) => tr && t.trim() !== tr.segments[Number(i)].text.trim());
  const shown = (tr?.segments ?? []).map((s, i) => ({ s, i })).filter(({ s, i }) => !filter || (draft[i] ?? s.text).toLowerCase().includes(filter.toLowerCase()));

  function play(t: number) {
    const v = player.current;
    if (!v) return;
    v.currentTime = Math.max(0, t - 0.3);
    v.play().catch(() => undefined);
  }

  async function save() {
    setBusy(true);
    try {
      const r = await api.editTranscript(id, changed.map(([i, text]) => ({ index: Number(i), text })));
      notify(`Saved ${r.segments_changed} line${r.segments_changed === 1 ? "" : "s"}${r.clips_changed ? `; ${r.clips_changed} clip${r.clips_changed === 1 ? "" : "s"} get new captions` : ""}.`);
      await load();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Link href={`/videos/${id}`} className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ChevronLeft size={16} /> {video.data?.title ?? "Video"}
      </Link>
      <PageHeader
        eyebrow="Stage 02 · Understand"
        title="Transcript"
        description="Correct what was heard. Captions follow the transcript, so clips that contain a corrected line are re-rendered. Changing a word keeps its timing; adding or removing words spreads the line's time over the new words."
        actions={
          editable && (
            <Button variant="primary" disabled={!changed.length || busy} onClick={save}>
              {busy ? "Saving…" : changed.length ? `Save ${changed.length} change${changed.length === 1 ? "" : "s"}` : "No changes"}
            </Button>
          )
        }
      />
      {error && <p role="alert" className="rounded bg-rec/10 p-3 text-sm text-rec">{error}</p>}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <Card padded={false} title={tr ? `${tr.segments.length} lines · ${tr.engine}${tr.words_estimated ? " · word times estimated" : ""}` : "Loading…"} actions={<input aria-label="Find in transcript" placeholder="Find…" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-40 rounded border border-line bg-paper px-2 py-1 text-sm" />}>
          {tr && !tr.segments.length && <div className="p-5"><EmptyNote>This video has no speech in its transcript.</EmptyNote></div>}
          <ol className="divide-y divide-line">
            {shown.map(({ s, i }) => {
              const value = draft[i] ?? s.text;
              const dirty = draft[i] !== undefined && draft[i].trim() !== s.text.trim();
              return (
                <li key={i} className={cx("grid grid-cols-[64px_minmax(0,1fr)] gap-2 px-4 py-2", dirty && "bg-accent-soft/50")}>
                  <button onClick={() => play(s.start)} className="flex h-fit items-center gap-1 pt-1.5 font-mono text-xs text-muted hover:text-accent" aria-label={`Play from ${fmtDuration(s.start)}`}>
                    <Play size={11} /> {fmtDuration(s.start)}
                  </button>
                  <span className="flex flex-col gap-1">
                    <textarea
                      aria-label={`Line ${i + 1}`}
                      value={value}
                      readOnly={!editable}
                      rows={Math.max(1, Math.ceil(value.length / 80))}
                      onChange={(e) => setDraft({ ...draft, [i]: e.target.value })}
                      className="w-full resize-y rounded border border-transparent bg-transparent px-2 py-1 text-sm hover:border-line focus:border-accent focus:bg-surface"
                    />
                    <span className="flex flex-wrap gap-1 px-2">
                      {s.speaker && <Badge>{s.speaker}</Badge>}
                      {s.edited && <Badge tone="accent">edited</Badge>}
                      {inClip.get(i)?.map((n) => <Badge key={n} tone="free">in clip: {n}</Badge>)}
                    </span>
                  </span>
                </li>
              );
            })}
          </ol>
        </Card>
        <div className="flex flex-col gap-3 lg:sticky lg:top-6 lg:self-start">
          <video ref={player} controls playsInline preload="metadata" src={proxyUrl(id)} className="aspect-video w-full rounded-md border border-line bg-ink" />
          <p className="text-xs text-muted">Click a time to hear that line. To fix the same word everywhere at once, use “Fix a word everywhere” in any clip of this video.</p>
        </div>
      </div>
    </>
  );
}
