"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Load data, and reload every `intervalMs` while `active(data)` is true. Never overlaps requests. */
export function usePoll<T>(load: () => Promise<T>, opts: { intervalMs?: number; active?: (d: T | undefined) => boolean; deps?: unknown[] } = {}) {
  const { intervalMs = 3000, active = () => true, deps = [] } = opts;
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const busy = useRef(false);
  const loadRef = useRef(load);
  loadRef.current = load;
  const activeRef = useRef(active);
  activeRef.current = active;

  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const d = await loadRef.current();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible" && activeRef.current(data)) refresh();
    }, intervalMs);
    return () => window.clearInterval(t);
  }, [data, intervalMs, refresh]);

  return { data, error, loading, refresh, setData };
}
