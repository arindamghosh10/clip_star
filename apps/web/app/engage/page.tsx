"use client";

import { useState } from "react";
import { EyeOff, Send } from "lucide-react";
import { Badge, Button, Card, EmptyNote, PageHeader, PlatformBadge, Tabs, Toggle } from "@/components/ui";
import type { CommentCategory } from "@/lib/data";
import { useStore } from "@/lib/store";

const catTone: Record<CommentCategory, "accent" | "free" | "paid" | "rec"> = {
  question: "accent",
  praise: "free",
  lead: "paid",
  spam: "rec",
};

export default function Engage() {
  const { comments, setComment, notify } = useStore();
  const [tab, setTab] = useState<CommentCategory | "all">("all");
  const [autoThanks, setAutoThanks] = useState(true);
  const [edits, setEdits] = useState<Record<string, string>>({});

  const open = comments.filter((c) => c.status === "open");
  const list = open.filter((c) => tab === "all" || c.category === tab);
  const count = (k: CommentCategory) => open.filter((c) => c.category === k).length;

  return (
    <>
      <PageHeader
        eyebrow="Stage 07 · Engage"
        title="Comments"
        description="Comments on your own posts, sorted and with replies drafted in your voice. Nothing is sent until you tap Send, except categories you allow."
      />

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <label className="flex items-center gap-2">
            <Toggle on={autoThanks} onChange={() => setAutoThanks(!autoThanks)} label="Auto-send replies to simple thanks" />
            Auto-send replies to simple &quot;thanks&quot; comments
          </label>
          <span className="text-muted">Limit: 30 replies per account per hour · own posts only</span>
        </div>
      </Card>

      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { id: "all", label: "All", count: open.length },
          { id: "question", label: "Questions", count: count("question") },
          { id: "lead", label: "Leads", count: count("lead") },
          { id: "praise", label: "Praise", count: count("praise") },
          { id: "spam", label: "Spam", count: count("spam") },
        ]}
      />

      <div className="flex flex-col gap-3">
        {list.length === 0 && <EmptyNote>All caught up.</EmptyNote>}
        {list.map((c) => (
          <Card key={c.id}>
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={catTone[c.category]}>{c.category}</Badge>
                <PlatformBadge platform={c.platform} />
                <span className="font-medium">{c.author}</span>
                <span className="text-muted">
                  on {c.account} · &quot;{c.clip}&quot; · {c.time} ago
                </span>
              </div>
              <p className="border-l-[3px] border-line pl-3">{c.text}</p>
              {c.category === "spam" ? (
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => {
                      setComment(c.id, { status: "hidden" });
                      notify("Comment hidden");
                    }}
                  >
                    <EyeOff size={14} /> Hide
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setComment(c.id, { status: "skipped" })}>
                    Not spam
                  </Button>
                </div>
              ) : (
                <>
                  <label className="flex flex-col gap-1 text-xs font-medium text-accent" htmlFor={`reply-${c.id}`}>
                    Drafted reply
                    <textarea
                      id={`reply-${c.id}`}
                      rows={2}
                      value={edits[c.id] ?? c.draft ?? ""}
                      onChange={(e) => setEdits({ ...edits, [c.id]: e.target.value })}
                      className="w-full rounded border border-accent/30 bg-accent-soft p-2 text-sm font-normal text-ink"
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => {
                        setComment(c.id, { status: "sent", draft: edits[c.id] ?? c.draft });
                        notify(`Reply sent to ${c.author}`);
                      }}
                    >
                      <Send size={14} /> Send
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setComment(c.id, { status: "skipped" })}>
                      Skip
                    </Button>
                  </div>
                </>
              )}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
