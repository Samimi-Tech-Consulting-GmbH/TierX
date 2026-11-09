"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { workflowRequest } from "@/lib/workflows";
import {
  ResourceLibrary,
  EditorBack,
  TenantSelection,
  studioButton,
} from "@/components/workflow-library";

type Tool = {
  name: string;
  description: string;
  input_schema: object;
  output_schema: object;
  retry_safe: boolean;
};
type Connector = {
  connector_code: string;
  name: string;
  kind: "rest" | "mcp";
  url: string;
  tenant_ids: string[];
  enabled: boolean;
  timeout_seconds: number;
  tools: Tool[];
  revision: number;
};
const initial: Connector = {
  connector_code: "",
  name: "",
  kind: "rest",
  url: "",
  tenant_ids: [],
  enabled: true,
  timeout_seconds: 30,
  tools: [],
  revision: 0,
};
const field = "mt-1 w-full rounded border bg-background p-2 text-sm";

export default function Page() {
  const { user } = useAuth();
  const [items, setItems] = useState<Connector[]>([]);
  const [value, setValue] = useState<Connector>(initial);
  const [credential, setCredential] = useState("");
  const [message, setMessage] = useState("");
  const [tools, setTools] = useState<Tool[]>([]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false),
    [loading, setLoading] = useState(true);
  async function load() {
    setItems(
      (await workflowRequest<{ items: Connector[] }>("/admin/connectors"))
        .items,
    );
  }
  useEffect(() => {
    if (user?.role === UserRole.PLATFORM_ADMIN)
      void load()
        .catch((error) => setMessage(error.message))
        .finally(() => setLoading(false));
  }, [user?.role]);
  async function act(task: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await task();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Operation failed");
    } finally {
      setBusy(false);
    }
  }
  if (user?.role !== UserRole.PLATFORM_ADMIN)
    return <p>Platform administrator access required.</p>;
  const original = items.find(
    (item) => item.connector_code === value.connector_code,
  );
  const dirty = Boolean(
    credential || JSON.stringify(value) !== JSON.stringify(original || initial),
  );
  if (!editing)
    return (
      <ResourceLibrary
        title="Tools & integrations"
        description="Connect approved REST and MCP providers. Agents and workflows can use only the tools you authorize."
        createLabel="Add integration"
        loading={loading}
        error={message}
        onCreate={() => {
          setValue(initial);
          setCredential("");
          setTools([]);
          setEditing(true);
          setMessage("");
        }}
        items={items.map((item) => ({
          id: item.connector_code,
          name: item.name,
          description: item.url,
          metadata:
            item.kind.toUpperCase() +
            " · " +
            item.tools.length +
            " approved tools · v" +
            item.revision,
          status: item.enabled ? "Enabled" : "Disabled",
          onOpen: () => {
            setValue(item);
            setCredential("");
            setTools([]);
            setEditing(true);
            setMessage("");
          },
        }))}
      />
    );
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-4 md:p-8">
      <EditorBack
        label="Back to integrations"
        onClick={() => {
          if (dirty && !confirm("Discard unsaved integration changes?")) return;
          setEditing(false);
          setCredential("");
          setMessage("");
        }}
      />
      <header className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">
          {value.name || "New integration"}
        </h1>
        <span className="rounded-full bg-muted px-3 py-1 text-xs">
          {dirty
            ? "Unsaved changes"
            : value.revision
              ? "Saved v" + value.revision
              : "Not saved"}
        </span>
      </header>
      <p className="text-sm text-muted-foreground">
        Register a REST or remote MCP provider, then explicitly approve the
        tools workflows may use. Credentials are encrypted and never returned.
      </p>
      {message && (
        <p role="status" className="rounded border p-3">
          {message}
        </p>
      )}
      <section className="rounded-xl border bg-card p-5">
        <h2 className="mb-5 text-lg font-semibold">Provider connection</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {(["connector_code", "name", "url"] as const).map((key) => (
            <label className="text-sm" key={key}>
              {
                {
                  connector_code: "Internal identifier",
                  name: "Display name",
                  url: "Provider URL",
                }[key]
              }
              <input
                className={field}
                disabled={key === "connector_code" && value.revision > 0}
                value={value[key]}
                onChange={(e) => setValue({ ...value, [key]: e.target.value })}
              />
            </label>
          ))}
          <label className="text-sm">
            Protocol
            <select
              className={field}
              value={value.kind}
              onChange={(e) =>
                setValue({ ...value, kind: e.target.value as "rest" | "mcp" })
              }
            >
              <option value="rest">REST · JSON POST</option>
              <option value="mcp">MCP · Streamable HTTP</option>
            </select>
          </label>
          <label className="text-sm">
            Bearer credential · leave empty to retain
            <input
              type="password"
              autoComplete="off"
              className={field}
              value={credential}
              onChange={(e) => setCredential(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Timeout (seconds)
            <input
              type="number"
              min={1}
              max={1800}
              className={field}
              value={value.timeout_seconds}
              onChange={(e) =>
                setValue({ ...value, timeout_seconds: e.target.valueAsNumber })
              }
            />
            {value.timeout_seconds > 300 && (
              <span className="block text-xs text-amber-500">
                This tool may delay the workflow for up to 30 minutes.
              </span>
            )}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={value.enabled}
              onChange={(e) =>
                setValue({ ...value, enabled: e.target.checked })
              }
            />
            Enabled
          </label>
        </div>
      </section>
      <TenantSelection
        multiple
        value={value.tenant_ids}
        onChange={(tenant_ids) => setValue({ ...value, tenant_ids })}
        disabled={busy}
      />
      <section className="space-y-3 rounded-xl border bg-card p-5">
        <h2 className="font-semibold">Approved tools</h2>
        {value.tools.map((tool, index) => (
          <fieldset key={index} className="space-y-3 rounded border p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm">
                Tool name
                <input
                  className={field}
                  value={tool.name}
                  onChange={(e) =>
                    setValue({
                      ...value,
                      tools: value.tools.map((v, i) =>
                        i === index ? { ...v, name: e.target.value } : v,
                      ),
                    })
                  }
                />
              </label>
              <label className="text-sm">
                Description
                <input
                  className={field}
                  value={tool.description}
                  onChange={(e) =>
                    setValue({
                      ...value,
                      tools: value.tools.map((v, i) =>
                        i === index ? { ...v, description: e.target.value } : v,
                      ),
                    })
                  }
                />
              </label>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={tool.retry_safe}
                onChange={(e) =>
                  setValue({
                    ...value,
                    tools: value.tools.map((v, i) =>
                      i === index ? { ...v, retry_safe: e.target.checked } : v,
                    ),
                  })
                }
              />
              Safe to repeat after an uncertain completion
            </label>
            {(["input_schema", "output_schema"] as const).map((key) => (
              <SchemaField
                key={key}
                label={key.replaceAll("_", " ")}
                value={tool[key]}
                onChange={(schema) =>
                  setValue({
                    ...value,
                    tools: value.tools.map((v, i) =>
                      i === index ? { ...v, [key]: schema } : v,
                    ),
                  })
                }
              />
            ))}
            <button
              className="text-sm text-destructive"
              onClick={() =>
                setValue({
                  ...value,
                  tools: value.tools.filter((_, i) => i !== index),
                })
              }
            >
              Remove tool
            </button>
          </fieldset>
        ))}
        <button
          className={studioButton}
          onClick={() =>
            setValue({
              ...value,
              tools: [
                ...value.tools,
                {
                  name: "",
                  description: "",
                  input_schema: {
                    type: "object",
                    properties: { value: { type: "string" } },
                    required: ["value"],
                    additionalProperties: false,
                  },
                  output_schema: { type: "object" },
                  retry_safe: false,
                },
              ],
            })
          }
        >
          Add tool definition
        </button>
      </section>
      <div className="flex gap-3">
        <button
          disabled={busy || !value.connector_code}
          className="rounded bg-primary p-2 text-primary-foreground"
          onClick={() =>
            void act(async () => {
              const {
                connector_code,
                revision,
                name,
                kind,
                url,
                tenant_ids,
                enabled,
                timeout_seconds,
                tools,
              } = value;
              const saved = await workflowRequest<Connector>(
                `/admin/connectors/${encodeURIComponent(connector_code)}`,
                "PUT",
                {
                  name,
                  kind,
                  url,
                  tenant_ids,
                  enabled,
                  timeout_seconds,
                  tools,
                  expected_revision: revision,
                  ...(credential ? { credential } : {}),
                },
              );
              setValue(saved);
              setCredential("");
              await load();
              setMessage(
                "Saved. Existing published flows retain their approved tool definitions.",
              );
            })
          }
        >
          Save integration
        </button>
        {value.kind === "mcp" && (
          <button
            disabled={busy || !value.revision || dirty}
            className="rounded border p-2"
            onClick={() =>
              void act(async () => {
                const result = await workflowRequest<{
                  tools: {
                    name: string;
                    description?: string;
                    inputSchema: object;
                    outputSchema?: object;
                  }[];
                }>(
                  `/admin/connectors/${value.connector_code}/discover`,
                  "POST",
                );
                setTools(
                  result.tools.map((tool) => ({
                    name: tool.name,
                    description: tool.description || tool.name,
                    input_schema: tool.inputSchema,
                    output_schema: tool.outputSchema || { type: "object" },
                    retry_safe: false,
                  })),
                );
                setMessage(
                  "Discovery succeeded. Select tools below, inspect their schemas, then save to approve.",
                );
              })
            }
          >
            Discover saved MCP server
          </button>
        )}
      </div>
      {tools.map((tool) => (
        <div
          key={tool.name}
          className="flex items-center justify-between rounded border p-3"
        >
          <span className="text-sm">
            {tool.name} — {tool.description}
          </span>
          <button
            className="rounded border p-2 text-sm"
            disabled={value.tools.some((v) => v.name === tool.name)}
            onClick={() =>
              setValue({ ...value, tools: [...value.tools, tool] })
            }
          >
            Select tool
          </button>
        </div>
      ))}
    </main>
  );
}

function SchemaField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: object;
  onChange: (value: object) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [error, setError] = useState("");
  const serialized = JSON.stringify(value);
  const [previous, setPrevious] = useState(serialized);
  if (serialized !== previous) {
    setPrevious(serialized);
    let equivalent = false;
    try {
      equivalent = JSON.stringify(JSON.parse(text)) === serialized;
    } catch {
      /* invalid local buffer */
    }
    if (!equivalent) {
      setText(JSON.stringify(value, null, 2));
      setError("");
    }
  }
  return (
    <details>
      <summary className="cursor-pointer text-sm">{label}</summary>
      <textarea
        aria-label={label}
        className={`${field} h-40 font-mono text-xs`}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const schema = JSON.parse(e.target.value);
            if (!schema || Array.isArray(schema) || typeof schema !== "object")
              throw new Error();
            onChange(schema);
            setError("");
          } catch {
            setError(
              "Enter a valid JSON schema object; invalid edits are not applied.",
            );
          }
        }}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </details>
  );
}
