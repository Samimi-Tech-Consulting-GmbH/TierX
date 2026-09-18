"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Braces,
  Check,
  Copy,
  ExternalLink,
  IdCard,
  LayoutDashboard,
  Plus,
  Save,
  UserCog,
} from "lucide-react";
import { toast } from "sonner";

import {
  getTenant,
  updateTenant,
  getAdminTenantOnboardingStatus,
  getTenantPipelineHealthSummary,
  ApiError,
} from "@/lib/api";
import {
  ALLOWED_TENANT_SOURCE_SYSTEMS,
  type TenantDocument,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/status-badge";
import { formatLocaleDateTime } from "@/lib/datetime";
import { PANEL, PANEL_NOTE, PANEL_TITLE } from "@/lib/cluster-display";
import { cn } from "@/lib/utils";
import { OnboardingChecklistCard } from "@/components/admin/onboarding-checklist-card";
import { PipelineHealthCard } from "@/components/admin/pipeline-health-card";
import type { PipelineHealthSummary } from "@/lib/types";
import { PlatformKpiRow } from "@/components/dashboard/platform-kpi-row";
import { useTenantDashboard } from "@/lib/use-tenant-dashboard";

export default function AdminTenantDetailPage() {
  const params = useParams<{ tenantId: string }>();
  const router = useRouter();
  const tenantId = params.tenantId;
  const dashboard = useTenantDashboard(tenantId);

  const [tenant, setTenant] = useState<TenantDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingSettingsJson, setSavingSettingsJson] = useState(false);

  const [displayName, setDisplayName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [sources, setSources] = useState<Set<string>>(new Set());

  const [settingsJson, setSettingsJson] = useState("{}");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const [onboarding, setOnboarding] = useState<Record<string, unknown>>({});
  const [pipeline, setPipeline] = useState<PipelineHealthSummary | null>(null);
  const [pipelineErr, setPipelineErr] = useState<string | null>(null);
  const [pipelineLoading, setPipelineLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getTenant(tenantId);
        if (cancelled) return;
        setTenant(data);
        setDisplayName(data.display_name);
        setContactEmail(data.contact_email ?? "");
        setSources(new Set(data.allowed_source_systems ?? []));
        setSettingsJson(JSON.stringify(data.settings ?? {}, null, 2));
        const ob = await getAdminTenantOnboardingStatus(tenantId).catch(
          () => ({}),
        );
        if (!cancelled) setOnboarding(ob);
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiError && err.status === 404) {
            toast.error("Tenant not found");
            router.push("/dashboard/admin/tenants");
          } else {
            toast.error("Failed to load tenant");
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [tenantId, router]);

  useEffect(() => {
    let cancelled = false;
    setPipelineLoading(true);
    setPipelineErr(null);
    getTenantPipelineHealthSummary(tenantId)
      .then((s) => {
        if (!cancelled) setPipeline(s);
      })
      .catch(() => {
        if (!cancelled) setPipelineErr("Could not load pipeline metrics.");
      })
      .finally(() => {
        if (!cancelled) setPipelineLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  function copy(text: string) {
    navigator.clipboard.writeText(text);
    toast.info("Copied");
  }

  function toggleSource(s: string) {
    setSources((prev) => {
      const n = new Set(prev);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });
  }

  async function saveProfile() {
    if (!tenant) return;
    setSavingProfile(true);
    try {
      const updated = await updateTenant(tenant.tenant_id, {
        display_name: displayName,
        contact_email: contactEmail || undefined,
        allowed_source_systems: Array.from(sources),
      });
      setTenant(updated);
      toast.success("Tenant updated");
    } catch {
      toast.error("Failed to save tenant");
    } finally {
      setSavingProfile(false);
    }
  }

  async function saveSettingsJson() {
    if (!tenant) return;
    setJsonError(null);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(settingsJson) as Record<string, unknown>;
      if (
        parsed === null ||
        typeof parsed !== "object" ||
        Array.isArray(parsed)
      ) {
        throw new Error("Settings must be a JSON object.");
      }
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "Invalid JSON syntax.");
      return;
    }

    setSavingSettingsJson(true);
    try {
      const updated = await updateTenant(tenant.tenant_id, {
        settings: parsed,
      });
      setTenant(updated);
      setSettingsJson(JSON.stringify(updated.settings ?? {}, null, 2));
      toast.success("Tenant updated");
    } catch {
      toast.error("Failed to save settings");
    } finally {
      setSavingSettingsJson(false);
    }
  }

  const profileDirty =
    tenant &&
    (displayName !== tenant.display_name ||
      contactEmail !== (tenant.contact_email ?? "") ||
      JSON.stringify([...sources].sort()) !==
        JSON.stringify([...(tenant.allowed_source_systems ?? [])].sort()));

  if (loading || !tenant) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Loading…
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start gap-4">
        <Button
          variant="ghost"
          size="icon"
          nativeButton={false}
          render={<Link href="/dashboard/admin/tenants" />}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">
              {tenant.display_name}
            </h1>
            <StatusBadge status={tenant.status} />
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div>
              <span className="text-muted-foreground">tenant_id · </span>
              <span className="font-mono">{tenant.tenant_id}</span>
              <button
                type="button"
                className="ml-2 inline text-muted-foreground hover:text-foreground"
                onClick={() => copy(tenant.tenant_id)}
              >
                <Copy className="inline h-3.5 w-3.5" />
              </button>
            </div>
            <div>
              <span className="text-muted-foreground">db_name · </span>
              <span className="font-mono">{tenant.db_name}</span>
              <button
                type="button"
                className="ml-2 inline text-muted-foreground hover:text-foreground"
                onClick={() => copy(tenant.db_name)}
              >
                <Copy className="inline h-3.5 w-3.5" />
              </button>
            </div>
            <div className="text-muted-foreground">
              Created{" "}
              <span className="text-foreground">
                {formatLocaleDateTime(tenant.created_at)}
              </span>
            </div>
          </div>
        </div>
        <Link
          href={`/dashboard/${tenant.tenant_id}`}
          className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md bg-[#404040] px-5 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
        >
          <LayoutDashboard className="size-4" />
          Go to Tenant Dashboard
          <ExternalLink className="size-3.5 opacity-60" />
        </Link>
      </div>

      <PlatformKpiRow
        summary={dashboard.summary}
        loading={dashboard.loading}
        error={dashboard.error}
      />

      <PipelineHealthCard
        tenantId={tenant.tenant_id}
        summary={pipeline}
        loading={pipelineLoading}
        error={pipelineErr}
      />

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <IdCard className="size-4 text-primary" />
          Identifiers
        </h3>
        <p className={PANEL_NOTE}>
          These values cannot be changed after the tenant is created.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <ReadRow label="Slug name (immutable)" value={tenant.name} />
          <ReadRow label="Tenant ID" value={tenant.tenant_id} mono />
          <ReadRow label="Database name" value={tenant.db_name} mono />
        </div>
      </div>

      <OnboardingChecklistCard data={onboarding} variant="admin" />

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <UserCog className="size-4 text-primary" />
          Editable profile
        </h3>
        <p className={PANEL_NOTE}>
          Display name, contact email, and permitted source systems.
        </p>
        <div className="mt-4 space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="pf-display" className="text-xs text-[#a3a3a3]">
                Display name
              </Label>
              <Input
                id="pf-display"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="h-10 bg-[#404040]"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pf-email" className="text-xs text-[#a3a3a3]">
                Contact email
              </Label>
              <Input
                id="pf-email"
                type="email"
                value={contactEmail}
                onChange={(e) => setContactEmail(e.target.value)}
                className="h-10 bg-[#404040]"
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]">
              Allowed source systems
            </Label>
            <div className="flex flex-wrap gap-2">
              {ALLOWED_TENANT_SOURCE_SYSTEMS.map((source) => {
                const on = sources.has(source);
                return (
                  <button
                    key={source}
                    type="button"
                    onClick={() => toggleSource(source)}
                    aria-pressed={on}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                      on
                        ? "bg-primary/20 text-foreground ring-1 ring-primary"
                        : "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]",
                    )}
                  >
                    {on ? (
                      <Check className="size-3.5 text-primary" />
                    ) : (
                      <Plus className="size-3.5 opacity-60" />
                    )}
                    {source}
                  </button>
                );
              })}
            </div>
          </div>

          <button
            type="button"
            onClick={() => void saveProfile()}
            disabled={savingProfile || !profileDirty}
            className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Save className="size-4" />
            {savingProfile ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <Braces className="size-4 text-primary" />
          Settings (JSON)
        </h3>
        <p className={PANEL_NOTE}>
          Tenant-level configuration overrides. Invalid JSON cannot be saved.
        </p>
        <div className="mt-4 space-y-3">
          <textarea
            className="min-h-[220px] w-full rounded-lg bg-[#171717] px-4 py-3 font-mono text-xs text-[#d4d4d4] outline-none ring-1 ring-transparent focus:ring-primary"
            value={settingsJson}
            onChange={(e) => {
              setSettingsJson(e.target.value);
              setJsonError(null);
            }}
            spellCheck={false}
          />
          {jsonError && <p className="text-sm text-destructive">{jsonError}</p>}
          <button
            type="button"
            onClick={() => void saveSettingsJson()}
            disabled={savingSettingsJson}
            className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Save className="size-4" />
            {savingSettingsJson ? "Saving…" : "Save settings JSON"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ReadRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-lg bg-[#404040] px-4 py-3">
      <div className="text-xs text-[#a3a3a3]">{label}</div>
      <div
        className={cn(
          "mt-1 truncate text-sm font-bold text-foreground",
          mono && "font-mono text-xs font-normal",
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}
