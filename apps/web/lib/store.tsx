"use client";

// In-memory UI state for the prototype. Lets buttons (approve, disable,
// send reply, change engine…) actually change what the screens show.
// Will be replaced by server state once the API exists.

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import {
  ACCOUNTS,
  BATCHES,
  CLIPS,
  COMMENTS,
  DEFAULT_ENGINES,
  RULES,
  type Account,
  type Batch,
  type BatchStatus,
  type Clip,
  type ClipStatus,
  type Comment,
  type Rule,
  type StageId,
} from "./data";

type Store = {
  clips: Clip[];
  setClipStatus: (id: string, status: ClipStatus) => void;
  batches: Batch[];
  setBatchStatus: (id: string, status: BatchStatus) => void;
  rules: Rule[];
  toggleRule: (id: string) => void;
  accounts: Account[];
  toggleAccountPaused: (id: string) => void;
  comments: Comment[];
  setComment: (id: string, patch: Partial<Comment>) => void;
  engines: Record<StageId, string>;
  setEngine: (stage: StageId, engineId: string) => void;
  toast: string | null;
  notify: (msg: string) => void;
};

const Ctx = createContext<Store | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [clips, setClips] = useState(CLIPS);
  const [batches, setBatches] = useState(BATCHES);
  const [rules, setRules] = useState(RULES);
  const [accounts, setAccounts] = useState(ACCOUNTS);
  const [comments, setComments] = useState(COMMENTS);
  const [engines, setEngines] = useState(DEFAULT_ENGINES);
  const [toast, setToast] = useState<string | null>(null);

  const value = useMemo<Store>(() => {
    const notify = (msg: string) => {
      setToast(msg);
      window.setTimeout(() => setToast((t) => (t === msg ? null : t)), 2600);
    };
    return {
      clips,
      setClipStatus: (id, status) => setClips((cs) => cs.map((c) => (c.id === id ? { ...c, status } : c))),
      batches,
      setBatchStatus: (id, status) => setBatches((bs) => bs.map((b) => (b.id === id ? { ...b, status } : b))),
      rules,
      toggleRule: (id) => setRules((rs) => rs.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r))),
      accounts,
      toggleAccountPaused: (id) =>
        setAccounts((as) =>
          as.map((a) => (a.id === id ? { ...a, status: a.status === "paused" ? "connected" : "paused" } : a)),
        ),
      comments,
      setComment: (id, patch) => setComments((ms) => ms.map((m) => (m.id === id ? { ...m, ...patch } : m))),
      engines,
      setEngine: (stage, engineId) => setEngines((e) => ({ ...e, [stage]: engineId })),
      toast,
      notify,
    };
  }, [clips, batches, rules, accounts, comments, engines, toast]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore must be used inside StoreProvider");
  return s;
}
