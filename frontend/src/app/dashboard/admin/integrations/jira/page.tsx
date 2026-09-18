"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Copy, Link2, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  ApiError,
  createJiraProjectRoute,
  createJiraSiteConnection,
  deleteJiraProjectRoute,
  listAlertTypeSchemas,
  listJiraProjectRoutes,
  listJiraSiteConnections,
  listTenants,
  revokeJiraSiteConnection,
  rotateJiraSiteConnection,
  setJiraProjectRouteEnabled,
  updateJiraProjectRoute,
} from "@/lib/api";
import type {
  AlertTypeSchemaDocument,
  JiraProjectRoute,
  JiraProjectRouteWrite,
  JiraSiteConnection,
  JiraSiteConnectionCreated,
  TenantDocument,
} from "@/lib/types";
import { TenantStatus } from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const EMPTY_ROUTE: JiraProjectRouteWrite = {
  project_key: "",
  tenant_id: "",
  source_system: "",
  alert_type: "",
  enabled: true,
};

function safeMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.detail
    : "The request could not be completed.";
}

export default function JiraIntegrationsPage() {
  const [connections, setConnections] = useState<JiraSiteConnection[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [routes, setRoutes] = useState<JiraProjectRoute[]>([]);
  const [tenants, setTenants] = useState<TenantDocument[]>([]);
  const [schemas, setSchemas] = useState<AlertTypeSchemaDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [connectionForm, setConnectionForm] = useState({
    name: "",
    jira_cloud_id: "",
    jira_site_url: "https://",
  });
  const [secretResult, setSecretResult] =
    useState<JiraSiteConnectionCreated | null>(null);
  const [routeOpen, setRouteOpen] = useState(false);
  const [editingRoute, setEditingRoute] = useState<JiraProjectRoute | null>(null);
  const [routeForm, setRouteForm] = useState<JiraProjectRouteWrite>(EMPTY_ROUTE);

  const selected = useMemo(
    () => connections.find((item) => item.integration_id === selectedId) ?? null,
    [connections, selectedId],
  );
  const selectedTenant = useMemo(
    () => tenants.find((item) => item.tenant_id === routeForm.tenant_id) ?? null,
    [routeForm.tenant_id, tenants],
  );

  const loadConnections = useCallback(async () => {
    const rows = await listJiraSiteConnections();
    setConnections(rows);
    setSelectedId((current) =>
      current && rows.some((row) => row.integration_id === current)
        ? current
        : (rows[0]?.integration_id ?? null),
    );
  }, []);

  const loadRoutes = useCallback(async (integrationId: string | null) => {
    if (!integrationId) {
      setRoutes([]);
      return;
    }
    setRoutes(await listJiraProjectRoutes(integrationId));
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const tenantRows = await listTenants({
          status: TenantStatus.ACTIVE,
          limit: 200,
        });
        if (!cancelled) setTenants(tenantRows);
        await loadConnections();
      } catch (error) {
        if (!cancelled) toast.error(safeMessage(error));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [loadConnections]);

  useEffect(() => {
    void loadRoutes(selectedId).catch((error) => toast.error(safeMessage(error)));
  }, [loadRoutes, selectedId]);

  useEffect(() => {
    if (!routeForm.tenant_id) {
      setSchemas([]);
      return;
    }
    void listAlertTypeSchemas(routeForm.tenant_id, {
      is_active: true,
      limit: 200,
    })
      .then((page) => setSchemas(page.items))
      .catch((error) => {
        setSchemas([]);
        toast.error(safeMessage(error));
      });
  }, [routeForm.tenant_id]);

  async function createConnection() {
    setBusy(true);
    try {
      const created = await createJiraSiteConnection(connectionForm);
      setSecretResult(created);
      setConnectionOpen(false);
      await loadConnections();
      setSelectedId(created.integration_id);
      setConnectionForm({ name: "", jira_cloud_id: "", jira_site_url: "https://" });
      toast.success("Jira site connection created");
    } catch (error) {
      toast.error(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  function openNewRoute() {
    setEditingRoute(null);
    setRouteForm(EMPTY_ROUTE);
    setRouteOpen(true);
  }

  function openEditRoute(route: JiraProjectRoute) {
    setEditingRoute(route);
    setRouteForm({
      project_key: route.project_key,
      tenant_id: route.tenant_id,
      source_system: route.source_system,
      alert_type: route.alert_type,
      enabled: route.enabled,
    });
    setRouteOpen(true);
  }

  async function saveRoute() {
    if (!selectedId) return;
    setBusy(true);
    try {
      if (editingRoute) {
        await updateJiraProjectRoute(
          selectedId,
          editingRoute.route_id,
          routeForm,
        );
      } else {
        await createJiraProjectRoute(selectedId, routeForm);
      }
      await Promise.all([loadRoutes(selectedId), loadConnections()]);
      setRouteOpen(false);
      toast.success(editingRoute ? "Project route updated" : "Project route created");
    } catch (error) {
      toast.error(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function toggleRoute(route: JiraProjectRoute) {
    if (!selectedId) return;
    try {
      await setJiraProjectRouteEnabled(selectedId, route.route_id, !route.enabled);
      await loadRoutes(selectedId);
      toast.success(route.enabled ? "Project route disabled" : "Project route enabled");
    } catch (error) {
      toast.error(safeMessage(error));
    }
  }

  async function removeRoute(route: JiraProjectRoute) {
    if (!selectedId || !window.confirm(`Delete route for ${route.project_key}?`)) return;
    try {
      await deleteJiraProjectRoute(selectedId, route.route_id);
      await Promise.all([loadRoutes(selectedId), loadConnections()]);
      toast.success("Project route deleted");
    } catch (error) {
      toast.error(safeMessage(error));
    }
  }

  async function rotateSecret() {
    if (!selectedId) return;
    setBusy(true);
    try {
      setSecretResult(await rotateJiraSiteConnection(selectedId));
      await loadConnections();
    } catch (error) {
      toast.error(safeMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function revokeConnection() {
    if (!selectedId || !window.confirm("Revoke this Jira site connection?")) return;
    try {
      await revokeJiraSiteConnection(selectedId);
      await loadConnections();
      toast.success("Jira site connection revoked");
    } catch (error) {
      toast.error(safeMessage(error));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">Jira Integrations</h1>
          <p className="text-muted-foreground">
            Connect Jira sites and route each project to a tenant, source system,
            and alert-type schema.
          </p>
        </div>
        <Button onClick={() => setConnectionOpen(true)}>
          <Plus className="size-4" /> New site connection
        </Button>
      </div>

      {loading ? (
        <div className="h-48 animate-pulse rounded-xl bg-card" />
      ) : connections.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            Create a Jira site connection, then add project routes.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <div className="space-y-3">
            {connections.map((connection) => (
              <button
                key={connection.integration_id}
                type="button"
                onClick={() => setSelectedId(connection.integration_id)}
                className={`w-full rounded-xl p-4 text-left ring-1 transition-colors ${
                  selectedId === connection.integration_id
                    ? "bg-primary/10 ring-primary"
                    : "bg-card ring-foreground/10 hover:bg-white/5"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-semibold">{connection.name}</span>
                  <Badge variant={connection.state === "ACTIVE" ? "success" : "destructive"}>
                    {connection.state}
                  </Badge>
                </div>
                <p className="mt-2 truncate font-mono text-xs text-muted-foreground">
                  {connection.jira_cloud_id}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {connection.route_count} project route{connection.route_count === 1 ? "" : "s"}
                </p>
              </button>
            ))}
          </div>

          {selected && (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>{selected.name}</CardTitle>
                  <CardDescription>{selected.jira_site_url || "Site URL not recorded"}</CardDescription>
                  <CardAction className="flex gap-2">
                    {selected.state === "ACTIVE" && (
                      <Button variant="outline" size="sm" onClick={() => void rotateSecret()} disabled={busy}>
                        <RefreshCw className="size-4" /> Rotate secret
                      </Button>
                    )}
                    <Button variant="destructive" size="sm" onClick={() => void revokeConnection()} disabled={selected.state === "REVOKED"}>
                      Revoke
                    </Button>
                  </CardAction>
                </CardHeader>
                <CardContent className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
                  <div><p className="text-muted-foreground">Cloud ID</p><p className="mt-1 break-all font-mono text-xs">{selected.jira_cloud_id}</p></div>
                  <div><p className="text-muted-foreground">Credential</p><p className="mt-1 font-mono text-xs">{selected.secret_prefix}…</p></div>
                  <div><p className="text-muted-foreground">Last connected</p><p className="mt-1">{selected.last_used_at ? formatLocaleDateTime(selected.last_used_at) : "Never"}</p></div>
                  <div><p className="text-muted-foreground">Last submission</p><p className="mt-1">{selected.last_submission_at ? formatLocaleDateTime(selected.last_submission_at) : "Never"}</p></div>
                </CardContent>
              </Card>

              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-xl font-semibold">Project routes</h2>
                  <p className="text-sm text-muted-foreground">Routing metadata is supplied by TierX, never by the Jira ticket.</p>
                </div>
                <Button onClick={openNewRoute} disabled={selected.state !== "ACTIVE"}>
                  <Plus className="size-4" /> Add route
                </Button>
              </div>

              {routes.length === 0 ? (
                <Card><CardContent className="py-10 text-center text-muted-foreground">No project routes are configured. Jira submissions will be rejected until a route exists.</CardContent></Card>
              ) : (
                <div className="space-y-3">
                  {routes.map((route) => (
                    <Card key={route.route_id} size="sm">
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                          <Link2 className="size-4" /> {route.project_key}
                          <Badge variant={route.enabled ? "success" : "secondary"}>{route.enabled ? "ENABLED" : "DISABLED"}</Badge>
                        </CardTitle>
                        <CardDescription>{route.tenant_name} · {route.source_system} · {route.alert_type}</CardDescription>
                        <CardAction className="flex gap-2">
                          <Button variant="outline" size="sm" onClick={() => void toggleRoute(route)}>{route.enabled ? "Disable" : "Enable"}</Button>
                          <Button variant="ghost" size="icon-sm" aria-label={`Edit ${route.project_key}`} onClick={() => openEditRoute(route)}><Pencil className="size-4" /></Button>
                          <Button variant="ghost" size="icon-sm" aria-label={`Delete ${route.project_key}`} onClick={() => void removeRoute(route)}><Trash2 className="size-4 text-destructive" /></Button>
                        </CardAction>
                      </CardHeader>
                      <CardContent className="grid gap-3 text-xs text-muted-foreground sm:grid-cols-3">
                        <span>Schema: {route.effective_schema_version ? `${route.effective_schema_id} · v${route.effective_schema_version}` : "Unavailable"}</span>
                        <span>Event time: {route.event_timestamp_path || "Unavailable"}</span>
                        <span>Revision: {route.revision}</span>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <Dialog open={connectionOpen} onOpenChange={setConnectionOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader><DialogTitle>New Jira site connection</DialogTitle><DialogDescription>Create the credential in TierX, then paste it once into the installed Jira app configuration.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2"><Label htmlFor="jira-name">Name</Label><Input id="jira-name" value={connectionForm.name} onChange={(event) => setConnectionForm((current) => ({ ...current, name: event.target.value }))} /></div>
            <div className="space-y-2"><Label htmlFor="jira-cloud">Jira cloud ID</Label><Input id="jira-cloud" value={connectionForm.jira_cloud_id} onChange={(event) => setConnectionForm((current) => ({ ...current, jira_cloud_id: event.target.value }))} /></div>
            <div className="space-y-2"><Label htmlFor="jira-url">Jira site URL</Label><Input id="jira-url" value={connectionForm.jira_site_url} onChange={(event) => setConnectionForm((current) => ({ ...current, jira_site_url: event.target.value }))} /></div>
          </div>
          <DialogFooter showCloseButton><Button onClick={() => void createConnection()} disabled={busy || !connectionForm.name || !connectionForm.jira_cloud_id || !connectionForm.jira_site_url.startsWith("https://")}>{busy ? "Creating…" : "Create connection"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={routeOpen} onOpenChange={setRouteOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader><DialogTitle>{editingRoute ? "Edit project route" : "Add project route"}</DialogTitle><DialogDescription>The selected route supplies all TierX metadata for raw Jira alert JSON.</DialogDescription></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2"><Label htmlFor="project-key">Jira project key</Label><Input id="project-key" value={routeForm.project_key} onChange={(event) => setRouteForm((current) => ({ ...current, project_key: event.target.value.toUpperCase() }))} /></div>
            <div className="space-y-2"><Label>Tenant</Label><Select items={tenants.map((tenant) => ({ value: tenant.tenant_id, label: tenant.display_name }))} value={routeForm.tenant_id || null} onValueChange={(value) => setRouteForm((current) => ({ ...current, tenant_id: value || "", source_system: "", alert_type: "" }))}><SelectTrigger className="w-full"><SelectValue placeholder="Select tenant" /></SelectTrigger><SelectContent>{tenants.map((tenant) => <SelectItem key={tenant.tenant_id} value={tenant.tenant_id}>{tenant.display_name}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label>Source system</Label><Select items={(selectedTenant?.allowed_source_systems ?? []).map((source) => ({ value: source, label: source }))} value={routeForm.source_system || null} onValueChange={(value) => setRouteForm((current) => ({ ...current, source_system: value || "" }))} disabled={!selectedTenant}><SelectTrigger className="w-full"><SelectValue placeholder="Select allowed source" /></SelectTrigger><SelectContent>{(selectedTenant?.allowed_source_systems ?? []).map((source) => <SelectItem key={source} value={source}>{source}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-2"><Label>Active alert type</Label><Select items={schemas.map((schema) => ({ value: schema.alert_type, label: `${schema.alert_type} · v${schema.version}` }))} value={routeForm.alert_type || null} onValueChange={(value) => setRouteForm((current) => ({ ...current, alert_type: value || "" }))} disabled={!routeForm.tenant_id}><SelectTrigger className="w-full"><SelectValue placeholder="Select active schema" /></SelectTrigger><SelectContent>{schemas.map((schema) => <SelectItem key={schema.schema_id} value={schema.alert_type}>{schema.alert_type} · v{schema.version}</SelectItem>)}</SelectContent></Select></div>
          </div>
          <DialogFooter showCloseButton><Button onClick={() => void saveRoute()} disabled={busy || !routeForm.project_key || !routeForm.tenant_id || !routeForm.source_system || !routeForm.alert_type}>{busy ? "Saving…" : "Save route"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(secretResult)} onOpenChange={(open) => !open && setSecretResult(null)}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader><DialogTitle>Copy the Jira connection credential now</DialogTitle><DialogDescription>The secret is shown once. Paste the ID and secret into Jira → Apps → Configure TierX.</DialogDescription></DialogHeader>
          {secretResult && <div className="space-y-4"><div className="space-y-2"><Label>Integration ID</Label><div className="flex gap-2"><Input readOnly value={secretResult.integration_id} className="font-mono text-xs" /><Button variant="outline" size="icon" aria-label="Copy integration ID" onClick={() => void navigator.clipboard.writeText(secretResult.integration_id)}><Copy className="size-4" /></Button></div></div><div className="space-y-2"><Label>Integration secret</Label><div className="flex gap-2"><Input readOnly value={secretResult.secret} className="font-mono text-xs" /><Button variant="outline" size="icon" aria-label="Copy integration secret" onClick={() => void navigator.clipboard.writeText(secretResult.secret)}><Copy className="size-4" /></Button></div></div></div>}
          <DialogFooter><Button onClick={() => setSecretResult(null)}>I saved the credential</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
