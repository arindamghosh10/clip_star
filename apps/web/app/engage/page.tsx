"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, EyeOff, RefreshCw, Send, X } from "lucide-react";
import { Badge, Button, Card, EmptyNote, PageHeader, PlatformBadge, Tabs, Toggle, cx } from "@/components/ui";
import { api, fmtTime, type ApiComment, type CommentCategory, type WorkspaceSettings } from "@/lib/api";
import { useStore } from "@/lib/store";
import { usePoll } from "@/lib/usePoll";

const catClass: Record<CommentCategory, string> = {
  question: "bg-accent-soft text-accent",
  lead: "bg-paid-soft text-paid",
  praise: "bg-free-soft text-free",
  critical: "bg-gate-soft text-gate",
  spam: "bg-rec/10 text-rec",
  other: "bg-paper text-muted",
};
const CATS: CommentCategory[] = ["question", "lead", "praise", "critical", "spam", "other"];
const replyLabel: Record<ApiComment["reply_status"], string> = { none: "", queued: "Reply waiting to send", sending: "Sending…", sent: "Replied", failed: "Reply failed", unknown: "Reply not confirmed" };

type Tab = CommentCategory | "all" | "done";

export default function Engage() {
  const { notify } = useStore();
  const [tab, setTab] = useState<Tab>("all");
  const list = usePoll(() => api.comments({ state: tab === "done" ? "done" : "open", category: tab === "all" || tab === "done" ? undefined : tab }), { intervalMs: 6000, deps: [tab] });
  const summary = usePoll(api.commentSummary, { intervalMs: 10000 });
  const open = summary.data?.open ?? {};
  const total = Object.values(open).reduce((a, b) => a + (b ?? 0), 0);
  const unsupported = (summary.data?.accounts ?? []).filter((a) => !a.supported);

  async function sync() {
    try {
      const r = await api.syncComments();
      notify(r.queued ? `Checking ${r.queued} account${r.queued > 1 ? "s" : ""} for new comments` : "No accounts with recent posts to check");
      setTimeout(() => (list.refresh(), summary.refresh()), 4000);
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }

  function replace(c: ApiComment) {
    list.setData((d) => d?.map((x) => (x.id === c.id ? c : x)).filter((x) => (tab === "done" ? x.state === "done" : x.state === "open")));
    summary.refresh();
  }

  return (
    <>
      <PageHeader
        eyebrow="Stage 07 · Engage"
        title="Comments"
        description="Comments on your own posts, sorted, with replies drafted in your voice. Nothing is sent until you tap Send, except categories you choose to auto-reply."
        actions={
          <Button onClick={sync}>
            <RefreshCw size={16} /> Check for new comments
          </Button>
        }
      />
      <AutoSettings />
      {!!summary.data?.needs_attention && (
        <p className="flex items-start gap-2 rounded bg-paid-soft p-3 text-sm text-paid">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {summary.data.needs_attention} repl{summary.data.needs_attention > 1 ? "ies" : "y"} failed or couldn&apos;t be confirmed. See the Handled tab.
        </p>
      )}
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { id: "all", label: "All open", count: total },
          ...CATS.map((c) => ({ id: c as Tab, label: c[0].toUpperCase() + c.slice(1), count: open[c] ?? 0 })),
          { id: "done", label: "Handled" },
        ]}
      />
      {list.error && <p className="text-sm text-rec">{list.error}</p>}
      <div className="flex flex-col gap-3">
        {!list.data ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : !list.data.length ? (
          <EmptyNote>{tab === "done" ? "Nothing handled yet." : "All caught up. New comments on your posts appear here."}</EmptyNote>
        ) : (
          list.data.map((c) => <CommentCard key={c.id} c={c} onChange={replace} />)
        )}
      </div>
      {unsupported.length > 0 && (
        <p className="text-xs text-muted">
          Not checked for comments: {unsupported.map((a) => `${a.handle} (${a.note})`).join(" · ")}
        </p>
      )}
    </>
  );
}

function CommentCard({ c, onChange }: { c: ApiComment; onChange: (c: ApiComment) => void }) {
  const { notify } = useStore();
  const [text, setText] = useState(c.draft);
  const [busy, setBusy] = useState(false);
  // keep what the user is typing; only take the server's draft when it actually changes
  useEffect(() => setText(c.draft), [c.draft]);

  async function act(fn: () => Promise<ApiComment>, ok: string) {
    setBusy(true);
    try {
      onChange(await fn());
      notify(ok);
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const tooLong = text.length > c.max_chars;
  const canSend = c.reply_status === "none" || c.reply_status === "failed";
  return (
    <Card>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <select
            aria-label="Category"
            value={c.category}
            onChange={(e) => act(() => api.updateComment(c.id, { category: e.target.value as CommentCategory }), "Category changed")}
            className={cx("rounded-full border-0 px-2 py-0.5 text-xs font-semibold", catClass[c.category])}
          >
            {CATS.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
          <PlatformBadge platform={c.platform} />
          <span className="font-medium">{c.author}</span>
          <span className="text-muted">
            on {c.handle}
            {c.clip_title ? ` · "${c.clip_title}"` : ""}
            {c.commented_at ? ` · ${fmtTime(c.commented_at)}` : ""}
          </span>
          {c.practice && <Badge>practice</Badge>}
          {c.hidden && <Badge tone="rec">hidden</Badge>}
          {c.reply_status !== "none" && <Badge tone={c.reply_status === "sent" ? "free" : c.reply_status === "failed" ? "rec" : c.reply_status === "unknown" ? "paid" : "accent"}>{replyLabel[c.reply_status]}{c.reply_auto ? " (auto)" : ""}</Badge>}
        </div>
        <p className="whitespace-pre-wrap border-l-[3px] border-line pl-3">{c.message}</p>
        {c.reply_status === "sent" || c.reply_status === "queued" || c.reply_status === "sending" ? (
          <p className="rounded bg-free-soft p-3 text-sm">
            <span className="font-medium">Your reply: </span>
            {c.reply_text}
          </p>
        ) : c.category === "spam" && c.state === "open" ? (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="danger" disabled={busy} onClick={() => act(() => api.commentAction(c.id, "hide"), "Hiding comment")}>
              <EyeOff size={14} /> Hide
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api.updateComment(c.id, { category: "other" }), "Marked as not spam")}>
              Not spam
            </Button>
          </div>
        ) : (
          <>
            <label htmlFor={`reply-${c.id}`} className="flex flex-col gap-1 text-xs font-medium text-accent">
              <span className="flex justify-between">
                {c.draft_by && c.draft_by !== "user" ? `Drafted by ${c.draft_by}` : "Your reply"}
                <span className={cx("font-mono", tooLong ? "text-rec" : "text-muted")}>
                  {text.length}/{c.max_chars}
                </span>
              </span>
              <textarea
                id={`reply-${c.id}`}
                rows={2}
                value={text}
                placeholder={c.category === "question" ? "Answer the question in your words…" : "Write a reply…"}
                onChange={(e) => setText(e.target.value)}
                className="w-full rounded border border-accent/30 bg-accent-soft p-2 text-sm font-normal text-ink"
              />
            </label>
            {c.error && (
              <p className="flex items-start gap-2 text-xs text-rec">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {c.error}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {canSend && (
                <Button size="sm" variant="primary" disabled={busy || !text.trim() || tooLong} onClick={() => act(() => api.sendReply(c.id, text), "Reply queued")}>
                  <Send size={14} /> Send
                </Button>
              )}
              {c.reply_status === "unknown" && (
                <>
                  <Button size="sm" disabled={busy} onClick={() => act(() => api.commentAction(c.id, "mark-sent"), "Marked as replied")}>
                    I see it posted
                  </Button>
                  <Button size="sm" variant="primary" disabled={busy || !text.trim()} onClick={() => act(() => api.sendReply(c.id, text, true), "Sending again")}>
                    It&apos;s not there, send again
                  </Button>
                </>
              )}
              {c.state === "open" ? (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api.commentAction(c.id, "skip"), "Skipped")}>
                  <X size={14} /> Skip
                </Button>
              ) : (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api.commentAction(c.id, "reopen"), "Back in the inbox")}>
                  Back to inbox
                </Button>
              )}
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

function AutoSettings() {
  const { notify } = useStore();
  const [s, setS] = useState<WorkspaceSettings | null>(null);
  useEffect(() => {
    api
      .workspace()
      .then((w) => setS(w.settings))
      .catch(() => setS({}));
  }, []);
  if (!s) return null;
  const cats = s.auto_reply_categories ?? [];

  async function save(patch: WorkspaceSettings, ok: string) {
    try {
      const w = await api.updateWorkspace({ settings: patch });
      setS(w.settings);
      notify(ok);
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e));
    }
  }
  const toggleCat = (c: "praise" | "lead") => {
    const next = cats.includes(c) ? cats.filter((x) => x !== c) : [...cats, c];
    save({ auto_reply_categories: next }, next.includes(c) ? `Auto-replying to ${c}` : `Stopped auto-replying to ${c}`);
  };

  return (
    <Card>
      <div className="grid gap-3 text-sm md:grid-cols-2 lg:grid-cols-4">
        <label className="flex items-center justify-between gap-3">
          <span>Auto-reply to praise</span>
          <Toggle on={cats.includes("praise")} onChange={() => toggleCat("praise")} label="Auto-reply to praise" />
        </label>
        <label className="flex items-center justify-between gap-3">
          <span>Auto-reply to business enquiries</span>
          <Toggle on={cats.includes("lead")} onChange={() => toggleCat("lead")} label="Auto-reply to business enquiries" />
        </label>
        <label className="flex items-center justify-between gap-3">
          <span>Hide spam automatically</span>
          <Toggle on={!!s.auto_hide_spam} onChange={() => save({ auto_hide_spam: !s.auto_hide_spam }, s.auto_hide_spam ? "Spam stays visible" : "Spam will be hidden")} label="Hide spam automatically" />
        </label>
        <label htmlFor="rph" className="flex items-center justify-between gap-3">
          <span>Replies per hour, per account</span>
          <input
            id="rph"
            type="number"
            min={1}
            max={200}
            defaultValue={s.replies_per_hour ?? 20}
            onBlur={(e) => {
              const n = Math.max(1, Math.min(200, Number(e.target.value) || 20));
              if (n !== (s.replies_per_hour ?? 20)) save({ replies_per_hour: n }, `Limit set to ${n} per hour`);
            }}
            className="w-20 rounded border border-line bg-paper px-2 py-1 text-right"
          />
        </label>
      </div>
      <label htmlFor="lead-reply" className="mt-3 flex flex-col gap-1 text-sm">
        <span className="text-xs text-muted">Reply used for business enquiries</span>
        <input
          id="lead-reply"
          defaultValue={s.lead_reply ?? "Thanks for reaching out! The best way to contact me is the link in my bio."}
          maxLength={500}
          onBlur={(e) => e.target.value.trim() && e.target.value !== s.lead_reply && save({ lead_reply: e.target.value.trim() }, "Business reply saved")}
          className="rounded border border-line bg-paper px-3 py-2"
        />
      </label>
      <p className="mt-2 text-xs text-muted">Auto-replies apply to new comments as they arrive. Questions and criticism are never sent automatically. Replies only go to comments on your own posts.</p>
    </Card>
  );
}
