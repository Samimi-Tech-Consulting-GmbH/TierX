"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Copy, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  ApiError,
  createEnrichmentAction,
  deleteEnrichmentAction,
  listEnrichmentActions,
  listTenantPage,
  rotateEnrichmentActionSecret,
  updateEnrichmentAction,
} from "@/lib/api";
import type {
  EnrichmentAction,
  EnrichmentActionCreated,
  EnrichmentActionWrite,
  TenantDocument,
} from "@/lib/types";
import { TenantStatus } from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const EMPTY: EnrichmentActionWrite = {
  action_code: "",
  name: "",
  description: "",
  url: "https://",
  timeout_seconds: 300,
  enabled: true,
  tenant_scope: "ALL_TENANTS",
  tenant_ids: [],
};

function safeMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.detail
    : "The request could not be completed.";
}

export default function EnrichmentActionsPage() {
  const [actions, setActions] = useState<EnrichmentAction[]>([]);
  const [tenants, setTenants] = useState<TenantDocument[]>([]);
  const [form, setForm] = useState<EnrichmentActionWrite>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [secret, setSecret] = useState<EnrichmentActionCreated | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const tenantNames = useMemo(
    () => new Map(tenants.map((tenant) => [tenant.tenant_id, tenant.display_name])),
    [tenants],
  );

  const load = useCallback(async () => {
    const [page, firstTenantPage] = await Promise.all([
      listEnrichmentActions(),
      listTenantPage({ status: TenantStatus.ACTIVE, skip: 0, limit: 200 }),
    ]);
    const remainingStarts = Array.from(
      { length: Math.max(0, Math.ceil(firstTenantPage.total / 200) - 1) },
      (_, index) => (index + 1) * 200,
    );
    const remainingPages = await Promise.all(
      remainingStarts.map((skip) =>
        listTenantPage({ status: TenantStatus.ACTIVE, skip, limit: 200 }),
      ),
    );
    setActions(page.items);
    setTenants([
      ...firstTenantPage.items,
      ...remainingPages.flatMap((tenantPage) => tenantPage.items),
    ]);
  }, []);

  useEffect(() => {
    void load()
      .catch((error) => toast.error(safeMessage(error)))
      .finally(() => setLoading(false));
  }, [load]);

  function reset() {
    setEditing(null);
    setForm(EMPTY);
  }

  function edit(action: EnrichmentAction) {
    setEditing(action.action_code);
    setForm({
      action_code: action.action_code,
      name: action.name,
      description: action.description,
      url: action.url,
      timeout_seconds: action.timeout_seconds,
      enabled: action.enabled,
      tenant_scope: action.tenant_scope,
      tenant_ids: action.tenant_ids,
    });
  }

  async function save() {
    setBusy(true);
    try {
      if (editing) {
        await updateEnrichmentAction(editing, {
          name: form.name,
          description: form.description,
          url: form.url,
          timeout_seconds: form.timeout_seconds,
          enabled: form.enabled,
          tenant_scope: form.tenant_scope,
          tenant_ids: form.tenant_ids,
        });
        toast.success("Enrichment action updated");
      } else {
        const created = await createEnrichmentAction(form);
        setSecret(created);
        toast.success("Enrichment action created");
      }
      reset();
      await load();
    } catch (error) {
      toast.error(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function rotate(action: EnrichmentAction) {
    if (!window.confirm(`Rotate the signing secret for ${action.action_code}?`)) return;
    try {
      setSecret(await rotateEnrichmentActionSecret(action.action_code));
      await load();
    } catch (error) {
      toast.error(safeMessage(error));
    }
  }

  async function remove(action: EnrichmentAction) {
    if (!window.confirm(`Delete ${action.action_code}? Existing results remain readable.`)) return;
    try {
      await deleteEnrichmentAction(action.action_code);
      await load();
      if (editing === action.action_code) reset();
    } catch (error) {
      toast.error(safeMessage(error));
    }
  }

  function toggleTenant(tenantId: string) {
    setForm((current) => ({
      ...current,
      tenant_ids: current.tenant_ids.includes(tenantId)
        ? current.tenant_ids.filter((id) => id !== tenantId)
        : [...current.tenant_ids, tenantId],
    }));
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Enrichment actions</h1>
        <p className="mt-2 text-muted-foreground">
          Register signed external context providers. Providers receive normalized
          alerts and return untrusted evidence for analysis prompts.
        </p>
      </div>

      {secret && (
        <Card className="border-amber-500/50">
          <CardHeader>
            <CardTitle>Copy this signing secret now</CardTitle>
            <CardDescription>
              It is shown once. Store it in the provider&apos;s secret manager; TierX
              will not reveal it again.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <code className="max-w-full overflow-x-auto rounded bg-black/30 px-3 py-2 text-xs">
              {secret.secret}
            </code>
            <Button
              variant="outline"
              onClick={() => {
                void navigator.clipboard.writeText(secret.secret);
                toast.success("Secret copied");
              }}
            >
              <Copy className="size-4" /> Copy
            </Button>
            <Button variant="ghost" onClick={() => setSecret(null)}>Dismiss</Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-3">
          {loading ? (
            <div className="h-48 animate-pulse rounded-xl bg-card" />
          ) : actions.length === 0 ? (
            <Card><CardContent className="py-12 text-center text-muted-foreground">No enrichment actions are configured.</CardContent></Card>
          ) : actions.map((action) => (
            <Card key={action.action_code}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle>{action.name}</CardTitle>
                    <CardDescription className="mt-1 font-mono">{action.action_code}</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Badge variant={action.enabled ? "success" : "secondary"}>{action.enabled ? "Enabled" : "Disabled"}</Badge>
                    <Button size="sm" variant="outline" onClick={() => edit(action)}><Pencil className="size-4" /> Edit</Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4 text-sm">
                <p>{action.description}</p>
                <dl className="grid gap-3 sm:grid-cols-2">
                  <div><dt className="text-muted-foreground">Endpoint</dt><dd className="break-all font-mono text-xs">{action.url}</dd></div>
                  <div><dt className="text-muted-foreground">Timeout</dt><dd>{action.timeout_seconds} seconds</dd></div>
                  <div><dt className="text-muted-foreground">Tenant access</dt><dd>{action.tenant_scope === "ALL_TENANTS" ? "All tenants" : action.tenant_ids.map((id) => tenantNames.get(id) ?? id).join(", ")}</dd></div>
                  <div><dt className="text-muted-foreground">Last execution</dt><dd>{action.last_used_at ? `${action.last_status} · ${formatLocaleDateTime(action.last_used_at)}` : "Never"}</dd></div>
                </dl>
                {action.last_error_type && <p className="text-destructive">Latest safe error: {action.last_error_type}</p>}
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => void rotate(action)}><RefreshCw className="size-4" /> Rotate secret</Button>
                  <Button size="sm" variant="destructive" onClick={() => void remove(action)}><Trash2 className="size-4" /> Delete</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle>{editing ? `Edit ${editing}` : "New enrichment action"}</CardTitle>
            <CardDescription>One integration represents exactly one action contract.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2"><Label htmlFor="action-code">Action code</Label><Input id="action-code" value={form.action_code} disabled={Boolean(editing)} placeholder="check-server-port" onChange={(event) => setForm({...form, action_code: event.target.value})} /></div>
            <div className="space-y-2"><Label htmlFor="action-name">Name</Label><Input id="action-name" value={form.name} onChange={(event) => setForm({...form, name: event.target.value})} /></div>
            <div className="space-y-2"><Label htmlFor="action-description">Description</Label><Input id="action-description" value={form.description} onChange={(event) => setForm({...form, description: event.target.value})} /></div>
            <div className="space-y-2"><Label htmlFor="action-url">Public HTTPS URL</Label><Input id="action-url" value={form.url} onChange={(event) => setForm({...form, url: event.target.value})} /></div>
            <div className="space-y-2"><Label htmlFor="action-timeout">Timeout (1–1800 seconds)</Label><Input id="action-timeout" type="number" min={1} max={1800} value={form.timeout_seconds} onChange={(event) => setForm({...form, timeout_seconds: Number(event.target.value)})} /></div>
            {form.timeout_seconds > 300 && <p role="alert" className="rounded-md border border-amber-500/50 bg-amber-500/10 p-3 text-sm text-amber-200">This action may delay correlation, analysis, and integration callbacks for up to 30 minutes.</p>}
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({...form, enabled: event.target.checked})} /> Enabled</label>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Tenant access</legend>
              <label className="flex items-center gap-2 text-sm"><input type="radio" checked={form.tenant_scope === "ALL_TENANTS"} onChange={() => setForm({...form, tenant_scope: "ALL_TENANTS", tenant_ids: []})} /> Allow all tenants</label>
              <label className="flex items-center gap-2 text-sm"><input type="radio" checked={form.tenant_scope === "SELECTED_TENANTS"} onChange={() => setForm({...form, tenant_scope: "SELECTED_TENANTS"})} /> Selected tenants</label>
              {form.tenant_scope === "SELECTED_TENANTS" && <div className="max-h-48 space-y-2 overflow-y-auto rounded border p-3">{tenants.map((tenant) => <label key={tenant.tenant_id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.tenant_ids.includes(tenant.tenant_id)} onChange={() => toggleTenant(tenant.tenant_id)} /> {tenant.display_name}</label>)}</div>}
            </fieldset>
            <div className="flex gap-2">
              <Button onClick={() => void save()} disabled={busy}><Plus className="size-4" /> {editing ? "Save" : "Create and generate secret"}</Button>
              {editing && <Button variant="ghost" onClick={reset}>Cancel</Button>}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
