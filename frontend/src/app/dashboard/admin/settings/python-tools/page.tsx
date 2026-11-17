"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { ToolNavigation } from "@/components/tool-navigation";
import { workflowRequest } from "@/lib/workflows";
import {
  ResourceLibrary,
  EditorBack,
  TenantSelection,
  studioButton,
  studioPrimary,
} from "@/components/workflow-library";

type Tool = {
  code: string;
  name: string;
  description: string;
  source: string;
  tenant_ids: string[];
  enabled: boolean;
  output_mode: "text" | "json";
  output_schema: Record<string, unknown>;
  timeout_seconds: number;
  destinations: { host: string; ports: number[] }[];
  draft_version?: number;
  active_revision?: number;
};
const initial: Tool = {
  code: "",
  name: "",
  description: "",
  tenant_ids: [],
  enabled: true,
  output_mode: "json",
  output_schema: { type: "object" },
  timeout_seconds: 30,
  destinations: [],
  source:
    'def run(alert: AlertContext, cluster: ClusterContext | None) -> dict:\n    return {"host": alert["normalized_payload"].get("host.name"), "clustered": cluster is not None}\n',
};
const field = "w-full rounded-lg border bg-background p-3 text-sm";
export default function PythonToolsPage() {
  const { user } = useAuth();
  const [items, setItems] = useState<Tool[]>([]),
    [draft, setDraft] = useState<Tool | null>(null);
  const [base, setBase] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("Code"),
    [network, setNetwork] = useState("[]"),
    [schema, setSchema] = useState('{"type":"object"}');
  const [sample, setSample] = useState(""),
    [testId, setTestId] = useState(""),
    [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [versions, setVersions] = useState<unknown[]>([]);
  const unsaved =
    !!draft &&
    (JSON.stringify(draft) !== base ||
      network !== JSON.stringify(draft.destinations, null, 2) ||
      schema !== JSON.stringify(draft.output_schema, null, 2));
  async function load() {
    const response = await workflowRequest<{ items: Tool[] }>(
      "/admin/python-tools",
    );
    setItems(response.items);
  }
  useEffect(() => {
    if (user?.role === "PLATFORM_ADMIN")
      load().catch(() => setMessage("Python tools could not be loaded."));
  }, [user?.role]);
  useEffect(() => {
    if (!unsaved) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [unsaved]);
  useEffect(() => {
    if (!testId || !draft) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const code = draft.code;
    async function poll() {
      try {
        const value = await workflowRequest<Record<string, unknown>>(
          `/admin/python-tools/${encodeURIComponent(code)}/tests/${testId}`,
          "GET",
          undefined,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setResult(value);
        if (["PENDING", "RUNNING"].includes(String(value.state)))
          timer = setTimeout(poll, 5000);
      } catch {
        if (!controller.signal.aborted)
          setMessage(
            "Test observation failed. The runner deadline still applies.",
          );
      }
    }
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [testId, draft?.code]); // eslint-disable-line react-hooks/exhaustive-deps
  if (user?.role !== "PLATFORM_ADMIN")
    return (
      <p>Python tool management requires platform administrator access.</p>
    );
  function open(value: Tool) {
    if (unsaved && !window.confirm("Discard unsaved Python tool changes?"))
      return;
    setDraft(value);
    setBase(JSON.stringify(value));
    setTab("Code");
    setNetwork(JSON.stringify(value.destinations, null, 2));
    setSchema(JSON.stringify(value.output_schema, null, 2));
    setTestId("");
    setResult(null);
    setVersions([]);
    setMessage("");
    setSample(
      JSON.stringify(
        {
          tenant_id: value.tenant_ids[0] || "",
          alert: {
            alert_id: "synthetic-python-test",
            tenant_id: value.tenant_ids[0] || "",
            alert_type: "synthetic",
            source_system: "TEST",
            normalized_payload: { "host.name": "EXAMPLE-HOST" },
          },
          cluster: null,
          members: [],
        },
        null,
        2,
      ),
    );
  }
  async function save() {
    if (!draft) return;
    setBusy(true);
    setMessage("");
    try {
      const payload = {
        name: draft.name,
        description: draft.description,
        source: draft.source,
        tenant_ids: draft.tenant_ids,
        enabled: draft.enabled,
        output_mode: draft.output_mode,
        timeout_seconds: draft.timeout_seconds,
        destinations: JSON.parse(network),
        output_schema: JSON.parse(schema),
      };
      const value = await workflowRequest<Tool>(
        `/admin/python-tools/${encodeURIComponent(draft.code)}`,
        "PUT",
        { ...payload, expected_version: draft.draft_version || 0 },
      );
      setDraft(value);
      setBase(JSON.stringify(value));
      setNetwork(JSON.stringify(value.destinations, null, 2));
      setSchema(JSON.stringify(value.output_schema, null, 2));
      setMessage("Draft saved. Publish to use this revision in new workflows.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }
  async function publish() {
    if (
      !draft ||
      !window.confirm(
        "Publish this Python code and network policy for authorized tenants?",
      )
    )
      return;
    setBusy(true);
    try {
      await workflowRequest(
        `/admin/python-tools/${draft.code}/publish`,
        "POST",
      );
      const published = { ...draft, active_revision: draft.draft_version };
      setDraft(published);
      setBase(JSON.stringify(published));
      await load();
      setMessage(
        "Published. Existing workflow runs keep their pinned revision.",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Publish failed");
    } finally {
      setBusy(false);
    }
  }
  async function test() {
    if (!draft) return;
    setBusy(true);
    setMessage("");
    try {
      const value = await workflowRequest<{ call_id: string; state: string }>(
        `/admin/python-tools/${draft.code}/test`,
        "POST",
        JSON.parse(sample),
      );
      setResult(value);
      setTestId(value.call_id);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Invalid input or test failed",
      );
    } finally {
      setBusy(false);
    }
  }
  if (!draft)
    return (
      <ResourceLibrary
        title="Python tools"
        navigation={<ToolNavigation active="python" />}
        description="Versioned Python functions in disposable containers. Only approved network destinations are reachable; no instance credentials or files are provided."
        createLabel="New Python tool"
        onCreate={() => open({ ...initial })}
        items={items.map((item) => ({
          id: item.code,
          name: item.name,
          description: item.description,
          metadata: `${item.code} · ${item.output_mode} · ${item.timeout_seconds}s`,
          status: item.enabled
            ? `Published ${item.active_revision || "—"}`
            : "Disabled",
          onOpen: () => open(item),
        }))}
        error={message}
      />
    );
  const update = (value: Partial<Tool>) => setDraft({ ...draft, ...value });
  return (
    <main className="mx-auto max-w-6xl space-y-5 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <EditorBack
          label="Back to Python tools"
          onClick={() => {
            if (!unsaved || window.confirm("Discard unsaved changes?"))
              setDraft(null);
          }}
        />
        <h1 className="min-w-0 flex-1 text-xl font-semibold">
          {draft.name || "New Python tool"}
        </h1>
        <span>{unsaved ? "Unsaved" : "Saved draft"}</span>
        <button className={studioButton} disabled={busy} onClick={save}>
          Save draft
        </button>
        <button
          className={studioPrimary}
          disabled={busy || unsaved || !draft.draft_version}
          onClick={publish}
        >
          Publish
        </button>
      </header>
      <nav
        aria-label="Python tool sections"
        className="flex gap-2 border-b pb-3"
      >
        {["Code", "Settings", "Test", "Versions"].map((name) => (
          <button
            key={name}
            className={studioButton}
            aria-pressed={tab === name}
            onClick={() => {
              setTab(name);
              if (name === "Versions" && draft.draft_version)
                workflowRequest<{ items: unknown[] }>(
                  `/admin/python-tools/${draft.code}/versions`,
                )
                  .then((v) => setVersions(v.items))
                  .catch(() => setMessage("Versions unavailable"));
            }}
          >
            {name}
          </button>
        ))}
      </nav>
      {message && (
        <p role="status" className="rounded border p-3">
          {message}
        </p>
      )}
      {tab === "Code" && (
        <section className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Define run(alert, cluster). Inputs are snapshots; cluster may be
            None. Return a string or dict matching the output mode. Standard
            library and tierx_tools.http_request / tcp_connect only; no
            installation secrets are available.
          </p>
          <label className="block">
            Python source
            <textarea
              spellCheck={false}
              aria-label="Python source"
              className={`${field} mt-2 min-h-[420px] font-mono`}
              value={draft.source}
              onChange={(e) => update({ source: e.target.value })}
            />
          </label>
        </section>
      )}
      {tab === "Settings" && (
        <section className="grid gap-5 md:grid-cols-2">
          <label>
            Immutable code
            <input
              className={field}
              disabled={!!draft.draft_version}
              value={draft.code}
              onChange={(e) => update({ code: e.target.value })}
            />
          </label>
          <label>
            Name
            <input
              className={field}
              value={draft.name}
              onChange={(e) => update({ name: e.target.value })}
            />
          </label>
          <label className="md:col-span-2">
            Description
            <textarea
              className={field}
              value={draft.description}
              onChange={(e) => update({ description: e.target.value })}
            />
          </label>
          <TenantSelection
            value={draft.tenant_ids}
            onChange={(tenant_ids) => update({ tenant_ids })}
            multiple
          />
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => update({ enabled: e.target.checked })}
            />
            Enabled (saving disable revokes new calls immediately)
          </label>
          <label>
            Timeout (seconds)
            <input
              className={field}
              type="number"
              min={1}
              max={1800}
              value={draft.timeout_seconds}
              onChange={(e) =>
                update({ timeout_seconds: e.target.valueAsNumber })
              }
            />
            {draft.timeout_seconds > 300 && (
              <p className="text-amber-400">
                This tool may delay the workflow for up to 30 minutes.
              </p>
            )}
          </label>
          <label>
            Output mode
            <select
              className={field}
              value={draft.output_mode}
              onChange={(e) =>
                update({ output_mode: e.target.value as Tool["output_mode"] })
              }
            >
              <option value="json">JSON object</option>
              <option value="text">Text evidence</option>
            </select>
          </label>
          <label>
            JSON output schema
            <textarea
              className={`${field} min-h-32 font-mono`}
              value={schema}
              onChange={(e) => setSchema(e.target.value)}
              onBlur={() => {
                try {
                  update({ output_schema: JSON.parse(schema) });
                } catch {
                  setMessage("Invalid output schema JSON; draft unchanged.");
                }
              }}
            />
          </label>
          <label>
            Approved network destinations
            <textarea
              aria-label="Approved network destinations"
              className={`${field} min-h-32 font-mono`}
              value={network}
              onChange={(e) => setNetwork(e.target.value)}
              onBlur={() => {
                try {
                  update({ destinations: JSON.parse(network) });
                } catch {
                  setMessage("Invalid destination JSON; draft unchanged.");
                }
              }}
            />
            <p className="text-xs">
              Example: [{`{"host":"api.example.com","ports":[443]}`}]. Empty
              means no outbound access. Protected infrastructure is always
              denied.
            </p>
          </label>
        </section>
      )}
      {tab === "Test" && (
        <section className="space-y-3">
          <p>
            Test the saved draft using explicit synthetic input. Network calls
            can have side effects.
          </p>
          <textarea
            aria-label="Test input JSON"
            className={`${field} min-h-64 font-mono`}
            value={sample}
            onChange={(e) => setSample(e.target.value)}
          />
          <button
            className={studioPrimary}
            disabled={busy || unsaved || !draft.draft_version}
            onClick={test}
          >
            Run test
          </button>
          {testId && ["PENDING", "RUNNING"].includes(String(result?.state)) && (
            <button
              className={studioButton}
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  setResult(
                    await workflowRequest(
                      `/admin/python-tools/${draft.code}/tests/${testId}`,
                      "DELETE",
                    ),
                  );
                } catch {
                  setMessage(
                    "Cancellation could not be confirmed; the runner deadline still applies.",
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              Cancel test
            </button>
          )}
          <pre className="max-h-96 overflow-auto rounded border p-3 text-xs">
            {JSON.stringify(result, null, 2)}
          </pre>
        </section>
      )}
      {tab === "Versions" && (
        <section>
          <h2 className="font-semibold">Immutable published revisions</h2>
          <pre className="max-h-[600px] overflow-auto text-xs">
            {JSON.stringify(versions, null, 2)}
          </pre>
        </section>
      )}
    </main>
  );
}
