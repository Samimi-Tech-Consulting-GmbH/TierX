"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { PlatformConfigurationForm, initialPlatformValues, type PlatformValues } from "@/components/platform-configuration-form";

const base = process.env.NEXT_PUBLIC_TIERX_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";

export default function InstallationPage() {
  const router = useRouter();
  const [values, setValues] = useState<PlatformValues>(initialPlatformValues);
  const [locked, setLocked] = useState<string[]>([]);
  const [token, setToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    fetch(`${base}/api/v1/installation/status`, { cache: "no-store" }).then(async (res) => {
      if (!res.ok) throw new Error("Installation status could not be loaded");
      const status = await res.json();
      if (!active) return;
      if (!status.wizard_available) { router.replace("/login"); return; }
      setValues(status.defaults); setLocked(status.locked_fields); setReady(true);
    }).catch((error) => { if (active) setMessage(error.message); });
    return () => { active = false; };
  }, [router]);
  async function send(action: "test" | "complete") {
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`${base}/api/v1/installation/${action}`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-TierX-Installation-Token": token },
        body: JSON.stringify(action === "test" ? values : { email, password, values }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Check the installation fields");
      if (action === "complete") { setToken(""); setPassword(""); router.replace("/login"); }
      else setMessage("Ollama connection and structured inference passed.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Installation failed"); }
    finally { setBusy(false); }
  }
  return <main className="mx-auto max-w-xl space-y-5 p-8">
    <h1 className="text-2xl font-bold">Install TierX</h1>
    <p>Enter the one-time token from the backend container logs. Database and internal connections are managed through deployment environment variables.</p>
    {message && <p role="status">{message}</p>}
    {ready && <form className="space-y-5" onSubmit={(event) => { event.preventDefault(); setReview(true); }}>
      <label className="block">Installation token<input required type="password" autoComplete="off" className="block w-full rounded border border-input bg-card p-2" value={token} onChange={(e) => setToken(e.target.value)} disabled={busy || review} /></label>
      <label className="block">Platform admin email<input required type="email" className="block w-full rounded border border-input bg-card p-2" value={email} onChange={(e) => setEmail(e.target.value)} disabled={busy || review} /></label>
      <label className="block">Platform admin password<input required minLength={12} maxLength={72} type="password" autoComplete="new-password" className="block w-full rounded border border-input bg-card p-2" value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy || review} /></label>
      <PlatformConfigurationForm values={values} locked={locked} onChange={setValues} disabled={busy || review} />
      {review ? <section className="space-y-3 rounded border border-border p-4">
        <h2>Review installation</h2><p>Administrator: {email}</p><p>TierX: {values.public_url}</p>
        <p>Ollama: {values.ollama_url} · {values.ollama_model}</p>
        <p>Analysis: {values.llm_analysis_enabled ? "Enabled (validated before completion)" : "Disabled"}</p>
        <p>Once completed, setup closes. Manage settings after signing in as platform admin.</p>
        <button type="button" disabled={busy} onClick={() => setReview(false)}>Back</button>
        <button type="button" className="ml-4 rounded bg-primary p-2 text-primary-foreground disabled:opacity-50" disabled={busy} onClick={() => void send("complete")}>{busy ? "Installing…" : "Complete installation"}</button>
      </section> : <div className="flex gap-4">
        <button type="button" className="rounded border border-input p-2" disabled={busy} onClick={() => void send("test")}>{busy ? "Checking…" : "Test Ollama connection"}</button>
        <button className="rounded bg-primary p-2 text-primary-foreground disabled:opacity-50" disabled={busy}>Review installation</button>
      </div>}
    </form>}
  </main>;
}
