"use client";

import { useRef, useState } from "react";
import { Music } from "lucide-react";
import { useAuth } from "./Auth";
import { FormError, Input, errText } from "./Form";
import { Button, Card, EmptyNote } from "./ui";
import { api, fmtDuration, musicUrl } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

export function MusicLibraryCard() {
  const { can } = useAuth();
  const { notify } = useStore();
  const tracks = usePoll(api.music, { intervalMs: 60000 });
  const ws = usePoll(api.workspace, { intervalMs: 60000 });
  const file = useRef<HTMLInputElement>(null);
  const [f, setF] = useState({ title: "", note: "", rights: false });
  const [picked, setPicked] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const edit = can("editor");
  const def = ws.data?.settings.default_music_id ?? "";
  const vol = ws.data?.settings.music_volume ?? 0.18;

  async function upload() {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      await api.uploadMusic(picked, f.title, f.note);
      setPicked(null);
      setF({ title: "", note: "", rights: false });
      tracks.refresh();
      notify("Track added");
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }
  async function setDefault(id: string, volume = vol) {
    try {
      await api.updateWorkspace({ settings: { default_music_id: id || null, music_volume: volume } });
      ws.refresh();
      notify(id ? "Default music set for new renders" : "No default music");
    } catch (e) {
      notify(errText(e));
    }
  }
  return (
    <Card title={<span className="flex items-center gap-2"><Music size={16} /> Music library</span>}>
      <div className="flex flex-col gap-3 text-sm">
        <p className="text-muted">Background music for clips, mixed quietly and ducked whenever someone speaks. Only add music you own or have a licence for; platforms can mute or block videos with music they recognise.</p>
        {edit && (
          <div className="flex flex-col gap-2 rounded border border-line p-3">
            <input ref={file} type="file" accept=".mp3,.m4a,.aac,.wav,.ogg,.oga,.opus,.flac,audio/*" className="hidden" onChange={(e) => { setPicked(e.target.files?.[0] ?? null); e.target.value = ""; }} />
            <Button size="sm" className="self-start" onClick={() => file.current?.click()}>{picked ? `Selected: ${picked.name}` : "Choose a track…"}</Button>
            {picked && (
              <>
                <Input id="mus-title" label="Title" placeholder={picked.name.replace(/\.[^.]+$/, "")} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
                <Input id="mus-note" label="Where it's from / licence" placeholder="e.g. Made it myself · Artlist licence #123" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
                <label className="flex items-start gap-2">
                  <input type="checkbox" className="mt-1" checked={f.rights} onChange={() => setF({ ...f, rights: !f.rights })} />
                  <span>I own this music or have a licence to use it in my videos on social platforms.</span>
                </label>
                <Button size="sm" variant="primary" className="self-start" disabled={!f.rights || busy} onClick={upload}>{busy ? "Adding…" : "Add track"}</Button>
              </>
            )}
            <FormError error={error} />
          </div>
        )}
        <ul className="flex flex-col">
          {tracks.data?.map((t) => (
            <li key={t.id} className="flex flex-col gap-1.5 border-b border-line py-2.5 last:border-0">
              <span className="flex items-center justify-between gap-2">
                <span className="min-w-0">
                  <span className="font-medium">{t.title}</span>
                  <span className="text-xs text-muted"> · {fmtDuration(t.duration_s)}{t.used_by ? ` · used by ${t.used_by}` : ""}{def === t.id ? " · default" : ""}</span>
                  {t.license_note && <span className="block truncate text-xs text-muted">{t.license_note}</span>}
                </span>
                {edit && (
                  <span className="flex shrink-0 gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setDefault(def === t.id ? "" : t.id)}>{def === t.id ? "Unset default" : "Make default"}</Button>
                    <Button size="sm" variant="danger" onClick={() => api.deleteMusic(t.id).then(() => { tracks.refresh(); notify("Track removed"); }).catch((e) => notify(errText(e)))}>Delete</Button>
                  </span>
                )}
              </span>
              <audio controls preload="none" src={musicUrl(t.id)} className="h-8 w-full" />
            </li>
          ))}
          {tracks.data && !tracks.data.length && <EmptyNote>No music yet.</EmptyNote>}
        </ul>
        {edit && def && (
          <label className="flex items-center gap-3">
            <span className="shrink-0">Default music level</span>
            <input type="range" min={0.05} max={0.5} step={0.01} defaultValue={vol} onMouseUp={(e) => setDefault(def, Number((e.target as HTMLInputElement).value))} onTouchEnd={(e) => setDefault(def, Number((e.target as HTMLInputElement).value))} className="flex-1" aria-label="Default music level" />
            <span className="w-10 text-right font-mono text-xs">{Math.round(vol * 100)}%</span>
          </label>
        )}
        <p className="text-xs text-muted">The default plays under every new render unless a clip version picks other music or none. Existing clips change only when re-rendered.</p>
      </div>
    </Card>
  );
}
