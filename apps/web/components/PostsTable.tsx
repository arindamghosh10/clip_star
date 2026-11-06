"use client";

import Link from "next/link";
import { ACCOUNTS, type Post, type PostStatus } from "@/lib/data";
import { Badge, EmptyNote, PlatformBadge } from "./ui";

const statusBadge: Record<PostStatus, { label: string; tone: "free" | "accent" | "rec" | "neutral" }> = {
  posted: { label: "Posted", tone: "free" },
  scheduled: { label: "Scheduled", tone: "accent" },
  failed: { label: "Failed", tone: "rec" },
  held: { label: "Held", tone: "neutral" },
};

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

export function PostsTable({ posts, showAccount = true }: { posts: Post[]; showAccount?: boolean }) {
  if (!posts.length) return <EmptyNote>No posts match these filters.</EmptyNote>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-sm">
        <thead>
          <tr className="border-b border-line text-left font-mono text-[11px] uppercase tracking-wider text-muted">
            {showAccount && <th className="px-5 py-2.5 font-medium">Account</th>}
            <th className="px-3 py-2.5 font-medium first:pl-5">Clip</th>
            <th className="px-3 py-2.5 font-medium">When</th>
            <th className="px-3 py-2.5 font-medium">Status</th>
            <th className="px-3 py-2.5 text-right font-medium">Views</th>
            <th className="px-3 py-2.5 text-right font-medium">Watched</th>
            <th className="px-3 py-2.5 text-right font-medium">Likes</th>
            <th className="px-3 py-2.5 text-right font-medium">Comments</th>
            <th className="px-3 py-2.5 text-right font-medium">Shares</th>
            <th className="px-5 py-2.5 text-right font-medium">Follows</th>
          </tr>
        </thead>
        <tbody className="tnum">
          {posts.map((p) => {
            const a = ACCOUNTS.find((x) => x.id === p.accountId)!;
            const st = statusBadge[p.status];
            const live = p.status === "posted";
            return (
              <tr key={p.id} className="border-b border-line last:border-0 hover:bg-paper">
                {showAccount && (
                  <td className="px-5 py-2.5">
                    <Link href={`/accounts/${a.id}`} className="flex items-center gap-2 font-medium hover:text-accent">
                      <PlatformBadge platform={a.platform} /> {a.handle}
                    </Link>
                  </td>
                )}
                <td className="px-3 py-2.5 first:pl-5">
                  <span className="font-medium">{p.clip}</span>{" "}
                  <span className="font-mono text-xs text-muted">
                    · {p.variant} · {p.batch}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted">{p.when}</td>
                <td className="px-3 py-2.5">
                  <Badge tone={st.tone}>{st.label}</Badge>
                </td>
                <td className="px-3 py-2.5 text-right font-mono">{live ? k(p.views) : "—"}</td>
                <td className="px-3 py-2.5 text-right font-mono">{live ? `${p.watched}%` : "—"}</td>
                <td className="px-3 py-2.5 text-right font-mono">{live ? k(p.likes) : "—"}</td>
                <td className="px-3 py-2.5 text-right font-mono">{live ? p.comments : "—"}</td>
                <td className="px-3 py-2.5 text-right font-mono">{live ? p.shares : "—"}</td>
                <td className="px-5 py-2.5 text-right font-mono">{live ? `+${p.follows}` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
