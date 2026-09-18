"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Building2,
  Copy,
  Loader2,
  Save,
  SlidersHorizontal,
} from "lucide-react";
import { toast } from "sonner";

import {
  getMyTenant,
  updateTenantSettingsSelfService,
  getTenantOnboardingSelfService,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PANEL, PANEL_NOTE, PANEL_TITLE } from "@/lib/cluster-display";
import { OnboardingChecklistCard } from "@/components/admin/onboarding-checklist-card";

export default function TenantSettingsPage() {
  const params = useParams<{ tenantId: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const tenantId = params.tenantId;

  const [contactEmail, setContactEmail] = useState("");
  const [displayNameReadonly, setDisplayNameReadonly] = useState("");
  const [similarity, setSimilarity] = useState("");
  const [workers, setWorkers] = useState("");
  const [model, setModel] = useState("");
  const [sourcesReadonly, setSourcesReadonly] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [onboarding, setOnboarding] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (!user) return;
    if (user.role === UserRole.PLATFORM_ADMIN) {
      router.replace(`/dashboard/admin/tenants/${tenantId}`);
      return;
    }
    if (user.role !== UserRole.TENANT_ADMIN) {
      toast.error("You do not have permission to access this page");
      router.replace(`/dashboard/${tenantId}`);
      return;
    }
    if (user.tenant_id !== tenantId) {
      router.replace(
        user.tenant_id ? `/dashboard/${user.tenant_id}/settings` : "/login",
      );
    }
  }, [user, tenantId, router]);

  useEffect(() => {
    if (!user || user.role !== UserRole.TENANT_ADMIN) return;
    if (user.tenant_id !== tenantId) return;

    let cancelled = false;
    Promise.all([
      getMyTenant(tenantId),
      getTenantOnboardingSelfService(tenantId).catch(() => ({})),
    ])
      .then(([t, ob]) => {
        if (cancelled) return;
        setDisplayNameReadonly(t.display_name);
        setContactEmail(t.contact_email ?? "");
        setSourcesReadonly(t.allowed_source_systems ?? []);
        const st = t.settings ?? {};
        setSimilarity(
          st.similarity_threshold != null
            ? String(st.similarity_threshold)
            : "",
        );
        setWorkers(
          st.worker_concurrency != null ? String(st.worker_concurrency) : "",
        );
        setModel(typeof st.default_model === "string" ? st.default_model : "");
        setOnboarding(ob as Record<string, unknown>);
      })
      .catch((e) => {
        if (!cancelled) {
          const msg =
            e instanceof ApiError ? e.detail : "Failed to load tenant";
          toast.error(msg);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [user, tenantId]);

  async function save() {
    const payload: {
      similarity_threshold?: number;
      worker_concurrency?: number;
      default_model?: string;
    } = {};

    if (similarity.trim()) {
      const v = Number(similarity);
      if (Number.isNaN(v) || v < 0 || v > 1) {
        toast.error("Similarity threshold must be between 0 and 1");
        return;
      }
      payload.similarity_threshold = v;
    }

    if (workers.trim()) {
      const w = parseInt(workers, 10);
      if (Number.isNaN(w) || w < 1) {
        toast.error("Worker concurrency must be a positive integer");
        return;
      }
      payload.worker_concurrency = w;
    }

    if (model.trim()) {
      payload.default_model = model.trim();
    }

    setSaving(true);
    try {
      await updateTenantSettingsSelfService(tenantId, {
        ...payload,
        contact_email: contactEmail.trim() || undefined,
      });
      toast.success("Tenant updated");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (
    !user ||
    user.role !== UserRole.TENANT_ADMIN ||
    user.tenant_id !== tenantId
  ) {
    return loading ? (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Loading…
      </div>
    ) : null;
  }

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
        Loading tenant settings…
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Tenant settings</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Manage contact details and processing preferences for your
          organization.
        </p>
      </div>

      <OnboardingChecklistCard data={onboarding} variant="tenant" />

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <Building2 className="size-4 text-primary" />
          Organization
        </h3>
        <p className={PANEL_NOTE}>
          Display name and integrations are managed by platform administrators.
        </p>
        <div className="mt-5 space-y-4">
          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]">Display name</Label>
            <Input
              value={displayNameReadonly}
              readOnly
              disabled
              className="h-10 bg-[#404040]"
            />
          </div>
          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]">Tenant ID</Label>
            <div className="flex items-center gap-2">
              <Input
                value={tenantId}
                readOnly
                className="h-10 bg-[#404040] font-mono text-sm"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => {
                  navigator.clipboard.writeText(tenantId);
                  toast.info("Copied");
                }}
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]" htmlFor="ts-email">
              Contact email
            </Label>
            <Input
              id="ts-email"
              type="email"
              className="h-10 bg-[#404040]"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]">
              Allowed source systems
            </Label>
            <p className="text-sm text-muted-foreground">
              {sourcesReadonly.length === 0
                ? "None configured."
                : sourcesReadonly.join(", ")}
            </p>
          </div>
        </div>
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <SlidersHorizontal className="size-4 text-primary" />
          Processing overrides
        </h3>
        <p className={PANEL_NOTE}>
          Optional tuning parameters stored in tenant settings.
        </p>
        <div className="mt-5 max-w-md space-y-4">
          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]" htmlFor="ts-sim">
              Similarity threshold (0.0 – 1.0)
            </Label>
            <Input
              id="ts-sim"
              className="h-10 bg-[#404040]"
              type="number"
              step="0.01"
              min={0}
              max={1}
              value={similarity}
              onChange={(e) => setSimilarity(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]" htmlFor="ts-workers">
              Worker concurrency
            </Label>
            <Input
              id="ts-workers"
              className="h-10 bg-[#404040]"
              type="number"
              min={1}
              step={1}
              value={workers}
              onChange={(e) => setWorkers(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label className="text-xs text-[#a3a3a3]" htmlFor="ts-model">
              Default model name
            </Label>
            <Input
              id="ts-model"
              className="h-10 bg-[#404040]"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="phi3"
            />
          </div>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving}
            className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Save className="size-4" />
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
