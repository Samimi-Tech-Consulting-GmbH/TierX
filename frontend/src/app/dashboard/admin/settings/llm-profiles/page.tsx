"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { workflowRequest } from "@/lib/workflows";
import {
  ResourceLibrary,
  EditorBack,
  TenantSelection,
} from "@/components/workflow-library";

type Profile = {
  profile_code: string;
  provider: string;
  base_url: string;
  model: string;
  tenant_ids: string[];
  allow_external_data: boolean;
  enabled: boolean;
  tool_mode: string;
  temperature: number;
  max_tokens: number;
  context_tokens: number;
  timeout_seconds: number;
  revision: number;
  tested?: boolean;
};
const initial: Profile = {
  profile_code: "local-analysis",
  provider: "ollama",
  base_url: "http://ollama:11434",
  model: "phi3:latest",
  tenant_ids: [],
  allow_external_data: false,
  enabled: true,
  tool_mode: "disabled",
  temperature: 0,
  max_tokens: 2048,
  context_tokens: 2048,
  timeout_seconds: 120,
  revision: 0,
};
export default function Page() {
  const { user } = useAuth();
  const [profiles, setProfiles] = useState<Profile[]>([]),
    [profile, setProfile] = useState(initial);
  const [apiKey, setApiKey] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    if (user?.role === UserRole.PLATFORM_ADMIN)
      workflowRequest<{ items: Profile[] }>("/admin/llm-profiles")
        .then((r) => setProfiles(r.items))
        .catch((e) => setMessage(e.message))
        .finally(() => setLoading(false));
  }, [user?.role]);
  async function submit(test = false) {
    setBusy(true);
    setMessage("");
    try {
      const revision = profile.revision;
      const fields = Object.fromEntries(
        Object.keys(initial)
          .filter((k) => k !== "revision")
          .map((k) => [k, profile[k as keyof Profile]]),
      );
      const row = test
        ? (
            await workflowRequest<{ profile: Profile }>(
              `/admin/llm-profiles/${profile.profile_code}/test`,
              "POST",
            )
          ).profile
        : await workflowRequest<Profile>(
            `/admin/llm-profiles/${profile.profile_code}`,
            "PUT",
            {
              ...fields,
              expected_revision: revision,
              ...(apiKey ? { api_key: apiKey } : {}),
            },
          );
      setProfile(row);
      setApiKey("");
      setProfiles(
        (await workflowRequest<{ items: Profile[] }>("/admin/llm-profiles"))
          .items,
      );
      setMessage(
        test
          ? "Configured protocol and structured inference passed."
          : "Saved. Test before referencing this revision in a workflow.",
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }
  if (user?.role !== UserRole.PLATFORM_ADMIN)
    return <p>Platform administrator access required.</p>;
  const original = profiles.find(
    (p) => p.profile_code === profile.profile_code,
  );
  const dirty = Boolean(
    apiKey || JSON.stringify(profile) !== JSON.stringify(original || initial),
  );
  if (!editing)
    return (
      <ResourceLibrary
        title="Model profiles"
        description="Choose the local or approved external models your agents and analysis steps can use. Test each saved profile before publishing a workflow."
        createLabel="Add model profile"
        loading={loading}
        error={message}
        onCreate={() => {
          setProfile(initial);
          setApiKey("");
          setEditing(true);
          setMessage("");
        }}
        items={profiles.map((p) => ({
          id: p.profile_code,
          name: p.profile_code,
          description:
            p.model +
            " · " +
            (p.provider === "ollama"
              ? "Local Ollama"
              : "OpenAI-compatible provider"),
          metadata:
            "v" +
            p.revision +
            " · " +
            p.tenant_ids.length +
            " authorized tenants",
          status: !p.enabled ? "Disabled" : p.tested ? "Tested" : "Needs test",
          onOpen: () => {
            setProfile({ ...p, context_tokens: p.context_tokens ?? 2048 });
            setApiKey("");
            setEditing(true);
            setMessage("");
          },
        }))}
      />
    );
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-4 md:p-8">
      <EditorBack
        label="Back to model profiles"
        onClick={() => {
          if (dirty && !confirm("Discard unsaved profile changes?")) return;
          setEditing(false);
          setApiKey("");
          setMessage("");
        }}
      />
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">
          {profile.revision ? profile.profile_code : "New model profile"}
        </h1>
        <span className="rounded-full bg-muted px-3 py-1 text-xs">
          {dirty ? "Unsaved changes" : profile.tested ? "Tested" : "Needs test"}
        </span>
      </header>
      <p className="text-sm leading-6 text-muted-foreground">
        Credentials are write-only and encrypted. External inference requires
        explicit tenant permission. JSON emulation is not native tool calling.
      </p>
      {message && <p role="status">{message}</p>}
      <section className="rounded-xl border bg-card p-5">
        <h2 className="mb-5 text-lg font-semibold">
          Model connection & limits
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {(["profile_code", "base_url", "model"] as const).map((field) => (
            <label key={field} className="space-y-1">
              {
                {
                  profile_code: "Profile identifier",
                  base_url: "Server URL",
                  model: "Model name",
                }[field]
              }
              <input
                className="w-full rounded border bg-background p-2"
                disabled={
                  busy || (field === "profile_code" && profile.revision > 0)
                }
                value={profile[field]}
                onChange={(e) =>
                  setProfile({ ...profile, [field]: e.target.value })
                }
              />
            </label>
          ))}
          <label>
            Provider
            <select
              className="w-full rounded border bg-background p-2"
              value={profile.provider}
              onChange={(e) =>
                setProfile({ ...profile, provider: e.target.value })
              }
            >
              <option value="ollama">Ollama</option>
              <option value="openai_compatible">
                OpenAI-compatible (include /v1 in base URL)
              </option>
            </select>
          </label>
          <label>
            Tool protocol
            <select
              className="w-full rounded border bg-background p-2"
              value={profile.tool_mode}
              onChange={(e) =>
                setProfile({ ...profile, tool_mode: e.target.value })
              }
            >
              <option value="disabled">Analysis only</option>
              <option value="native">Native tool calling</option>
              <option value="json_emulated">JSON-emulated tool calling</option>
            </select>
          </label>
          <label>
            Provider API key (leave empty to retain)
            <input
              type="password"
              autoComplete="off"
              className="w-full rounded border bg-background p-2"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>
          {(
            [
              "temperature",
              "max_tokens",
              "context_tokens",
              "timeout_seconds",
            ] as const
          ).map((field) => (
            <label key={field}>
              {
                {
                  temperature: "Temperature",
                  max_tokens: "Output token limit",
                  context_tokens: "Context window (tokens)",
                  timeout_seconds: "Timeout (seconds)",
                }[field]
              }
              <input
                type="number"
                className="w-full rounded border bg-background p-2"
                value={profile[field]}
                onChange={(e) =>
                  setProfile({ ...profile, [field]: Number(e.target.value) })
                }
              />
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={profile.allow_external_data}
              onChange={(e) =>
                setProfile({
                  ...profile,
                  allow_external_data: e.target.checked,
                })
              }
            />{" "}
            Permit external inference for the listed tenants
          </label>
          <label>
            <input
              type="checkbox"
              checked={profile.enabled}
              onChange={(e) =>
                setProfile({ ...profile, enabled: e.target.checked })
              }
            />{" "}
            Enabled
          </label>
        </div>
      </section>
      <TenantSelection
        multiple
        value={profile.tenant_ids}
        onChange={(tenant_ids) => setProfile({ ...profile, tenant_ids })}
        disabled={busy}
      />
      <div className="flex gap-3">
        <button
          disabled={busy}
          className="rounded-lg bg-primary px-4 py-2 text-primary-foreground"
          onClick={() => void submit()}
        >
          Save profile
        </button>
        <button
          disabled={busy || !profile.revision || dirty}
          className="rounded border p-2"
          onClick={() => void submit(true)}
        >
          Test saved profile
        </button>
      </div>
    </main>
  );
}
