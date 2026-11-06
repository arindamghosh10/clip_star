import { STAGES, type StageId } from "@/lib/data";
import { cx } from "./ui";

// Horizontal 9-stage pipeline. `current` highlights where a video is now.
export function PipelineRail({ current, compact = false }: { current?: StageId; compact?: boolean }) {
  const idx = current ? STAGES.findIndex((s) => s.id === current) : -1;
  return (
    <div className="overflow-x-auto pb-1">
      <ol className={cx("grid min-w-[900px] grid-cols-9", compact && "min-w-[720px]")}>
        {STAGES.map((s, i) => {
          const state = idx < 0 ? "idle" : i < idx ? "done" : i === idx ? "now" : "todo";
          return (
            <li
              key={s.id}
              className={cx(
                "relative flex flex-col gap-0.5 border-t-[3px] px-2.5 pb-2 pt-3",
                state === "done" && "border-free",
                state === "now" && "border-accent",
                (state === "todo" || state === "idle") && "border-ink/70",
                state === "todo" && "opacity-60",
              )}
            >
              <span
                aria-hidden
                className={cx(
                  "absolute -top-[8px] left-2.5 h-[13px] w-[13px] rounded-full border-[3px] bg-paper",
                  state === "done" && "border-free bg-free",
                  state === "now" && "animate-pulse border-accent",
                  (state === "todo" || state === "idle") && "border-ink/70",
                )}
              />
              {s.gated && (
                <span className="absolute -top-[11px] right-1 rounded bg-gate-soft px-1 font-mono text-[10px] text-gate">approval</span>
              )}
              <span className="font-mono text-[11px] text-muted">{String(i + 1).padStart(2, "0")}</span>
              <span className="text-sm font-semibold leading-tight">{s.name}</span>
              {!compact && <span className="text-xs leading-snug text-muted">{s.output}</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
