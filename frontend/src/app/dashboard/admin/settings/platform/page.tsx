"use client";

import { useEffect, useState } from "react";
import { useAuth, readToken } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { PlatformConfigurationForm, initialPlatformValues, type PlatformValues } from "@/components/platform-configuration-form";

const base = process.env.NEXT_PUBLIC_TIERX_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";
interface Configuration {
  values: PlatformValues; locked_fields: string[]; revision: number;
  services: { service: string; applied_revision: number; seen_at: string; stale?: boolean; configuration_error?: string }[];
}
async function request(method = "GET", body?: unknown, suffix = "") {
  const response = await fetch(`${base}/api/v1/admin/settings/platform${suffix}`, {
    method, cache: "no-store", headers: { "Content-Type": "application/json", Authorization: `Bearer ${readToken()}` },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Settings request failed");
  return result;
}

export default function PlatformSettingsPage() {
  const { user } = useAuth();
  const [config, setConfig] = useState<Configuration | null>(null);
  const [values, setValues] = useState(initialPlatformValues);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (user?.role !== UserRole.PLATFORM_ADMIN) return;
    let active = true;
    request().then((data) => { if (active) { setConfig(data); setValues(data.values); } })
      .catch((error) => { if (active) setMessage(error.message); });
    const interval = setInterval(() => {
      request().then((data) => { if (active) setConfig((current) => current ? { ...current, services: data.services } : data); })
        .catch((error) => { if (active) setMessage(error.message); });
    }, 5000);
    return () => { active = false; clearInterval(interval); };
  }, [user?.role]);
  async function save(test = false) {
    if (!config) return;
    setBusy(true); setMessage("");
    try {
      const result = await request(test ? "POST" : "PUT", test ? values : { values, expected_revision: config.revision }, test ? "/test" : "");
      if (!test) { setConfig(result); setValues(result.values); }
      setMessage(test ? "Ollama connection and structured inference passed." : "Settings saved. Services apply the revision after active jobs finish.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Save failed"); }
    finally { setBusy(false); }
  }
  if (user?.role !== UserRole.PLATFORM_ADMIN) return <p>Platform administrator access required.</p>;
  return <main className="max-w-2xl space-y-5 p-6">
    <h1 className="text-2xl font-bold">Platform Settings</h1>
    <p>MongoDB, Kafka, internal addresses, and encryption keys are managed by deployment environment variables.</p>
    {message && <p role="status">{message}</p>}
    {config && <><p>Saved revision: {config.revision}</p>
      <PlatformConfigurationForm values={values} locked={config.locked_fields} onChange={setValues} disabled={busy} />
      <div className="flex gap-4"><button className="rounded border border-input p-2" disabled={busy} onClick={() => void save(true)}>Test Ollama connection</button>
        <button className="rounded bg-primary p-2 text-primary-foreground disabled:opacity-50" disabled={busy} onClick={() => void save()}>{busy ? "Applying…" : "Save settings"}</button></div>
      <h2>Service configuration</h2>
      {config.services.map((service) => <p key={service.service}>{service.service}: revision {service.applied_revision} · {service.configuration_error ||
        (service.stale ? "Heartbeat stale" :
          service.applied_revision === config.revision ? "Applied" : "Awaiting revision")} · last seen {service.seen_at}</p>)}
    </>}
  </main>;
}
