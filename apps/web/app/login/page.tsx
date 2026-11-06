"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { useAuth } from "@/components/Auth";
import { FormError, Input, Panel, errText } from "@/components/Form";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";

function Login() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(email, password);
      await refresh();
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) {
      setError(errText(err));
      setBusy(false);
    }
  }

  return (
    <Panel title="Sign in" description="Use the email and password you set up for clip_star.">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Input id="email" label="Email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input id="password" label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <FormError error={error} />
        <Button variant="primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="text-xs text-muted">Forgot your password? Ask an owner to send you a new invite link from Settings → Team.</p>
    </Panel>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
