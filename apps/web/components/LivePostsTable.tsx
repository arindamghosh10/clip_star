"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ExternalLink } from "lucide-react";
import { api, fmtTime, type ApiPost, type PostStatus } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";
import { Badge, Button, EmptyNote, PlatformBadge } from "./ui";

const tone: Record<PostStatus, "free" | "accent" | "rec" | "neutral" | "paid" | "gate"> = {
  held: "neutral",
  scheduled: "accent",
  publishing: "gate",
  published: "free",
  failed: "rec",
  unknown: "paid",
  cancelled: "neutral",
};
const label: Record<PostStatus, string> = {
  held: "Waiting for approval",
  scheduled: "Scheduled",
  publishing: "Publishing…",
  published: "Posted",
  failed: "Failed",
  unknown: "Checking",
  cancelled: "Cancelled",
};

export type PostFilter = { account_id?: string; platform?: string; group?: string; clip_id?: string; batch_id?: string; status?: string };

export function LivePostsTable({ filter, showAccount = true }: { filter: PostFilter; showAccount?: boolean }) {
  const { notify } = useStore();
  const key = JSON.stringify(filter);
  const posts = usePoll(() => api.posts({ ...filter, limit: 500 }), { intervalMs: 5000, deps: [key] });
  const accounts = usePoll(api.accounts, { intervalMs: 60000 });
  const clips = usePoll(() => api.clips(), { intervalMs: 60000 });
  const acc = useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a])), [accounts.data]);
  const cl = useMemo(() => new Map((clips.data ?? []).map((c) => [c.id, c])), [clips.data]);

  async function act(p: ApiPost, action: "retry" | "cancel" | "mark-published", ok: string) {
    try {
      await api.postAction(p.id, action);
      notify(ok);
      posts.refresh();
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }

  if (posts.error) return <p className="p-5 text-sm text-rec">{posts.error}</p>;
  if (!posts.data) return <p className="p-5 text-sm text-muted">Loading…</p>;
  if (!posts.data.length) {
    return (
      <div className="p-5">
        <EmptyNote>No posts here yet.</EmptyNote>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] text-sm">
        <thead>
          <tr className="border-b border-line text-left font-mono text-[11px] uppercase tracking-wider text-muted">
            {showAccount && <th className="px-5 py-2.5 font-medium">Account</th>}
            <th className="px-3 py-2.5 font-medium first:pl-5">Clip</th>
            <th className="px-3 py-2.5 font-medium">When</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-5 py-2.5 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {posts.data.map((p) => {
            const a = acc.get(p.account_id);
            const c = cl.get(p.clip_id);
            return (
              <tr key={p.id} className="border-b border-line align-top last:border-0">
                {showAccount && (
                  <td className="px-5 py-2.5">
                    {a ? (
                      <Link href={`/accounts/${a.id}`} className="flex items-center gap-2 font-medium hover:text-accent">
                        <PlatformBadge platform={a.platform} /> {a.handle}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                )}
                <td className="max-w-xs px-3 py-2.5 first:pl-5">
                  <Link href={`/clips/${p.clip_id}`} className="font-medium hover:text-accent">
                    {c?.title ?? "Clip"}
                  </Link>
                  <span className="font-mono text-xs text-muted"> · {p.variant}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted">{fmtTime(p.published_at ?? p.scheduled_at)}</td>
                <td className="max-w-sm px-3 py-2.5">
                  <span className="flex flex-col gap-1">
                    <span className="flex items-center gap-2">
                      <Badge tone={tone[p.status]}>{label[p.status]}</Badge>
                      {p.remote_url && (
                        <a href={p.remote_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent">
                          View <ExternalLink size={12} />
                        </a>
                      )}
                      {p.attempts > 1 && <span className="font-mono text-xs text-muted">try {p.attempts}</span>}
                    </span>
                    {p.last_error && <span className={`text-xs ${p.status === "failed" ? "text-rec" : "text-muted"}`}>{p.last_error}</span>}
                  </span>
                </td>
                <td className="px-5 py-2.5">
                  <span className="flex flex-wrap justify-end gap-1">
                    {p.status === "unknown" && (
                      <Button size="sm" onClick={() => act(p, "mark-published", "Marked as posted")}>
                        I see it posted
                      </Button>
                    )}
                    {(p.status === "failed" || p.status === "unknown") && (
                      <Button size="sm" variant="primary" onClick={() => act(p, "retry", "Will retry now")}>
                        Retry
                      </Button>
                    )}
                    {["held", "scheduled", "failed", "unknown"].includes(p.status) && (
                      <Button size="sm" variant="ghost" onClick={() => act(p, "cancel", "Post cancelled")}>
                        Cancel
                      </Button>
                    )}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
