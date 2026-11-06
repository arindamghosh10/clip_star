"use client";

import Link from "next/link";
import { useState } from "react";
import { ClipCard } from "@/components/ClipCard";
import { Button, EmptyNote, PageHeader, Tabs } from "@/components/ui";
import type { ClipStatus } from "@/lib/data";
import { useStore } from "@/lib/store";

export default function Clips() {
  const { clips, setClipStatus, notify } = useStore();
  const [tab, setTab] = useState<ClipStatus | "all">("pending");
  const list = clips.filter((c) => tab === "all" || c.status === tab).sort((a, b) => b.score - a.score);
  const pending = clips.filter((c) => c.status === "pending");

  return (
    <>
      <PageHeader
        eyebrow="Stages 03–05"
        title="Clips"
        description="Every clip comes with a score, the reason it was picked, and copy for each platform."
        actions={
          <>
            {pending.length > 0 && (
              <Button
                variant="primary"
                onClick={() => {
                  pending.forEach((c) => setClipStatus(c.id, "approved"));
                  notify(`Approved ${pending.length} clips`);
                }}
              >
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
          { id: "approved", label: "Approved", count: clips.filter((c) => c.status === "approved").length },
          { id: "rejected", label: "Rejected", count: clips.filter((c) => c.status === "rejected").length },
          { id: "all", label: "All", count: clips.length },
        ]}
      />
      <div className="flex flex-col gap-3">
        {list.length ? list.map((c) => <ClipCard key={c.id} clip={c} />) : <EmptyNote>Nothing here right now.</EmptyNote>}
      </div>
    </>
  );
}
