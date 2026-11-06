"use client";

import type { InputHTMLAttributes, ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

export function Input({ label, hint, id, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; id: string }) {
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-sm">
      <span className="text-muted">{label}</span>
      <input id={id} {...props} className="rounded border border-line bg-paper px-3 py-2 disabled:opacity-60" />
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function FormError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="flex items-start gap-2 rounded bg-rec/10 p-3 text-sm text-rec">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" /> {error}
    </p>
  );
}

export function Panel({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex w-full max-w-md flex-col gap-4 rounded-md border border-line bg-surface p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted">{description}</p>}
      </div>
      {children}
    </section>
  );
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
