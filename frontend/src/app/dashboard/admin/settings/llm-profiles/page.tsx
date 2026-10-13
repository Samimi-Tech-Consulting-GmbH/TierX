"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { workflowRequest } from "@/lib/workflows";

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
  useEffect(() => {
    if (user?.role === UserRole.PLATFORM_ADMIN)
      workflowRequest<{ items: Profile[] }>("/admin/llm-profiles")
        .then((r) => setProfiles(r.items))
        .catch((e) => setMessage(e.message));
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
  return (
    <main className="max-w-3xl space-y-4 p-6">
      <h1 className="text-2xl font-bold">V2 LLM profiles</h1>
      <p>
        Credentials are write-only and encrypted. External inference requires
        explicit tenant permission. JSON emulation is not native tool calling.
      </p>
      {message && <p role="status">{message}</p>}
      <div className="flex flex-wrap gap-2">
        <button
          className="rounded border p-2"
          onClick={() => {
            setProfile(initial);
            setApiKey("");
          }}
        >
          New profile
        </button>
        {profiles.map((p) => (
          <button
            className="rounded border p-2"
            key={p.profile_code}
            onClick={() => {
              setProfile(p);
              setApiKey("");
            }}
          >
            {p.profile_code} · r{p.revision} ·{" "}
            {p.tested ? "Tested" : "Untested"}
          </button>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {(["profile_code", "base_url", "model"] as const).map((field) => (
          <label key={field} className="space-y-1">
            {field.replaceAll("_", " ")}
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
          Authorized tenant IDs (comma-separated)
          <input
            className="w-full rounded border bg-background p-2"
            value={profile.tenant_ids.join(",")}
            onChange={(e) =>
              setProfile({
                ...profile,
                tenant_ids: e.target.value
                  .split(",")
                  .map((v) => v.trim())
                  .filter(Boolean),
              })
            }
          />
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
        {(["temperature", "max_tokens", "timeout_seconds"] as const).map(
          (field) => (
            <label key={field}>
              {field.replaceAll("_", " ")}
              <input
                type="number"
                className="w-full rounded border bg-background p-2"
                value={profile[field]}
                onChange={(e) =>
                  setProfile({ ...profile, [field]: Number(e.target.value) })
                }
              />
            </label>
          ),
        )}
        <label>
          <input
            type="checkbox"
            checked={profile.allow_external_data}
            onChange={(e) =>
              setProfile({ ...profile, allow_external_data: e.target.checked })
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
      <div className="flex gap-3">
        <button
          disabled={busy}
          className="rounded border p-2"
          onClick={() => void submit()}
        >
          Save profile
        </button>
        <button
          disabled={busy || !profile.revision}
          className="rounded border p-2"
          onClick={() => void submit(true)}
        >
          Test saved profile
        </button>
      </div>
    </main>
  );
}
