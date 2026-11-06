"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { LiveClipCard } from "@/components/LiveClipCard";
import { Button, EmptyNote, PageHeader, Tabs } from "@/components/ui";
import { api, type ApiClip } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

type Tab = ApiClip["status"] | "all";

export default function Clips() {
  const { notify } = useStore();
  const [tab, setTab] = useState<Tab>("pending");
  const clips = usePoll(() => api.clips(), {
    intervalMs: 4000,
    active: (d) => !!d?.some((c) => c.status !== "rejected" && c.variants.some((v) => !c.meta.renders?.[v.id] && !c.meta.render_errors?.[v.id])),
  });
  const all = clips.data ?? [];
  const list = all.filter((c) => tab === "all" || c.status === tab);
  const pending = all.filter((c) => c.status === "pending");
  const count = (s: ApiClip["status"]) => all.filter((c) => c.status === s).length;

  function replace(c: ApiClip) {
    clips.setData((d) => d?.map((x) => (x.id === c.id ? c : x)));
  }

  async function approveAll() {
    try {
      const updated = await Promise.all(pending.map((c) => api.updateClip(c.id, { status: "approved" })));
      clips.setData((d) => d?.map((x) => updated.find((u) => u.id === x.id) ?? x));
      notify(`Approved ${updated.length} clips`);
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
      clips.refresh();
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Stages 03–04"
        title="Clips"
        description="Every clip comes with a score, the reason it was picked, and its rendered versions. Approve the ones you want to publish."
        actions={
          <>
            {pending.length > 0 && (
              <Button variant="primary" onClick={approveAll}>
                Approve all {pending.length}
              </Button>
            )}
            <Link href="/publishing">
              <Button>Go to publishing</Button>
            </Link>
          </>
        }
      />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { id: "pending", label: "Needs approval", count: pending.length },
          { id: "approved", label: "Approved", count: count("approved") },
          { id: "rejected", label: "Rejected", count: count("rejected") },
          { id: "all", label: "All", count: all.length },
        ]}
      />
      {clips.error && (
        <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {clips.error}
        </p>
      )}
      <div className="flex flex-col gap-3">
        {clips.loading && !clips.data ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : list.length ? (
          list.map((c) => <LiveClipCard key={c.id} clip={c} onChange={replace} showVideoLink />)
        ) : (
          <EmptyNote>{all.length ? "Nothing here right now." : "No clips yet. Upload a video and clips appear here after the Find moments and Edit stages."}</EmptyNote>
        )}
      </div>
    </>
  );
}
