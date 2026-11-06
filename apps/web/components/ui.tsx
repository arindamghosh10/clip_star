"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { PLATFORMS, type Platform } from "@/lib/data";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex max-w-2xl flex-col gap-1">
        {eyebrow && <span className="font-mono text-xs uppercase tracking-wider text-muted">{eyebrow}</span>}
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
        {description && <p className="text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, actions, children, className, padded = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={cx("min-w-0 rounded-md border border-line bg-surface", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
          {title && <h2 className="font-semibold">{title}</h2>}
          {actions}
        </div>
      )}
      <div className={padded ? "p-5" : ""}>{children}</div>
    </section>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({ variant = "secondary", size = "md", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        variant === "primary" && "bg-accent text-surface hover:bg-accent/90",
        variant === "secondary" && "border border-line bg-surface hover:bg-paper",
        variant === "ghost" && "text-muted hover:bg-paper hover:text-ink",
        variant === "danger" && "border border-line bg-surface text-rec hover:bg-rec/10",
        className,
      )}
    />
  );
}

type Tone = "neutral" | "free" | "paid" | "gate" | "accent" | "rec" | "solid";

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold",
        tone === "neutral" && "border border-line text-muted",
        tone === "free" && "bg-free-soft text-free",
        tone === "paid" && "bg-paid-soft text-paid",
        tone === "gate" && "bg-gate-soft text-gate",
        tone === "accent" && "bg-accent-soft text-accent",
        tone === "rec" && "bg-rec/10 text-rec",
        tone === "solid" && "bg-ink text-paper",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Dot({ tone }: { tone: "ok" | "warn" | "off" | "bad" }) {
  return (
    <span
      aria-hidden
      className={cx(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        tone === "ok" && "bg-free",
        tone === "warn" && "bg-paid",
        tone === "off" && "bg-line",
        tone === "bad" && "bg-rec",
      )}
    />
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onChange}
      className={cx(
        "relative h-5 w-9 shrink-0 rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        on ? "bg-free" : "bg-line",
      )}
    >
      <span className={cx("absolute top-0.5 h-4 w-4 rounded-full bg-surface shadow transition-all", on ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cx("h-1.5 overflow-hidden rounded-full bg-line", className)}>
      <div className="h-full rounded-full bg-accent" style={{ width: `${value}%` }} />
    </div>
  );
}

export function Stat({ label, value, delta }: { label: string; value: string; delta?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-md border border-line bg-surface p-4">
      <span className="text-xs text-muted">{label}</span>
      <span className="tnum text-2xl font-bold">{value}</span>
      {delta && <span className="text-xs font-medium text-free">{delta}</span>}
    </div>
  );
}

const platformTone: Record<Platform, string> = {
  instagram: "bg-[#E1306C]/10 text-[#C1275C] dark:text-[#F07AA5]",
  facebook: "bg-[#1877F2]/10 text-[#1565D0] dark:text-[#7FB0FF]",
  tiktok: "bg-ink/10 text-ink",
  youtube: "bg-[#FF0000]/10 text-[#CC0000] dark:text-[#FF7A7A]",
  x: "bg-ink/10 text-ink",
  linkedin: "bg-[#0A66C2]/10 text-[#0A66C2] dark:text-[#79B4F0]",
  threads: "bg-ink/10 text-ink",
  pinterest: "bg-[#E60023]/10 text-[#C4001E] dark:text-[#FF7A8C]",
};

export function PlatformBadge({ platform, full = false }: { platform: Platform; full?: boolean }) {
  return (
    <span className={cx("inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold", platformTone[platform])}>
      {full ? PLATFORMS[platform].label : PLATFORMS[platform].short}
    </span>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  const tone = score >= 80 ? "free" : score >= 65 ? "paid" : "neutral";
  return (
    <Badge tone={tone} className="tnum font-mono">
      {score}
    </Badge>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: string; count?: number }[] }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
      {items.map((it) => (
        <button
          key={it.id}
          role="tab"
          aria-selected={value === it.id}
          onClick={() => onChange(it.id)}
          className={cx(
            "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            value === it.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {it.label}
          {it.count !== undefined && <span className="ml-1.5 font-mono text-xs text-muted">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="rounded border border-dashed border-line p-6 text-center text-sm text-muted">{children}</p>;
}
