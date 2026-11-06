"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useAuth } from "@/components/Auth";
import { FormError, Input, Panel, errText } from "@/components/Form";
import { Button } from "@/components/ui";
import { api, type Role } from "@/lib/api";

function Invite() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const { refresh } = useAuth();
  const [info, setInfo] = useState<{ email: string; name: string; role: Role; workspace: string } | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("This link is missing its code. Open the full link from your invite.");
      return;
    }
    api
      .inviteInfo(token)
      .then((i) => {
        setInfo(i);
        setName(i.name);
      })
      .catch((e) => setError(errText(e)));
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(token, name, password);
      await refresh();
      router.replace("/");
    } catch (err) {
      setError(errText(err));
      setBusy(false);
    }
  }

  return (
    <Panel title={info ? `Join ${info.workspace}` : "Join clip_star"} description={info ? `You're invited as ${info.role}. Choose a password to finish.` : undefined}>
      {info && (
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Input id="email" label="Email" value={info.email} disabled />
          <Input id="name" label="Your name" required value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          <Input id="password" label="Password" type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" hint="At least 10 characters." />
          <FormError error={error} />
          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? "Joining…" : "Join"}
          </Button>
        </form>
      )}
      {!info && <FormError error={error} />}
    </Panel>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Invite />
    </Suspense>
  );
}
