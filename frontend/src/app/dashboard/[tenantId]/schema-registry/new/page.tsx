"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Upload } from "lucide-react";
import { toast } from "sonner";

import {
  createAlertTypeSchemaFromYaml,
  getAlertTypeSchemaById,
  getMyTenant,
  listPlaybooks,
  listTenants,
  ApiError,
} from "@/lib/api";
import {
  buildAlertTypeSchemaYamlFromDocument,
  extractAlertTypeFromYamlText,
} from "@/lib/alert-type-schema-yaml";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import type { PlaybookListItem, TenantDocument } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PANEL, PANEL_NOTE, PANEL_TITLE } from "@/lib/cluster-display";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function NewAlertTypeSchemaPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground text-sm">
          Loading…
        </div>
      }
    >
      <NewAlertTypeSchemaPageHarness />
    </Suspense>
  );
}

function NewAlertTypeSchemaPageHarness() {
  const searchParams = useSearchParams();
  const params = useParams<{ tenantId: string }>();
  const cloneFrom = searchParams.get("cloneFrom")?.trim() ?? "";
  return (
    <NewAlertTypeSchemaPageContent
      key={`${params.tenantId}:${cloneFrom || "new"}`}
      cloneFrom={cloneFrom}
    />
  );
}

function NewAlertTypeSchemaPageContent({ cloneFrom }: { cloneFrom: string }) {
  const params = useParams<{ tenantId: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const routeTenantId = params.tenantId;

  const isPlatformAdmin = user?.role === UserRole.PLATFORM_ADMIN;

  const [selectedTenantId, setSelectedTenantId] = useState(routeTenantId);
  const [tenants, setTenants] = useState<TenantDocument[]>([]);
  const [playbooks, setPlaybooks] = useState<PlaybookListItem[]>([]);
  const [playbooksLoading, setPlaybooksLoading] = useState(false);
  const [playbookId, setPlaybookId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [expectedAlertType, setExpectedAlertType] = useState<string | null>(
    null,
  );
  const [fileAlertType, setFileAlertType] = useState<string | null>(null);
  const [fileParseError, setFileParseError] = useState<string | null>(null);
  const [tenantDisplayName, setTenantDisplayName] = useState<
    string | undefined
  >(undefined);
  const playbooksRef = useRef<PlaybookListItem[]>([]);
  playbooksRef.current = playbooks;

  const effectiveTenantId = isPlatformAdmin
    ? selectedTenantId
    : (user?.tenant_id ?? "");

  useEffect(() => {
    setSelectedTenantId(routeTenantId);
  }, [routeTenantId]);

  useEffect(() => {
    if (!isPlatformAdmin) return;
    listTenants({ limit: 500 })
      .then(setTenants)
      .catch(() => {
        toast.error("Could not load tenants");
      });
  }, [isPlatformAdmin]);

  useEffect(() => {
    let cancelled = false;
    if (!effectiveTenantId) {
      setTenantDisplayName(undefined);
      return;
    }
    getMyTenant(effectiveTenantId)
      .then((t) => {
        if (!cancelled) setTenantDisplayName(t.display_name);
      })
      .catch(() => {
        if (!cancelled) setTenantDisplayName(effectiveTenantId);
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveTenantId]);

  useEffect(() => {
    if (!effectiveTenantId) {
      setPlaybooks([]);
      setPlaybookId("");
      return;
    }
    let cancelled = false;
    setPlaybooksLoading(true);
    setPlaybookId("");
    listPlaybooks(effectiveTenantId, { limit: 500 })
      .then((rows) => {
        if (!cancelled) setPlaybooks(rows);
      })
      .catch(() => {
        if (!cancelled) {
          setPlaybooks([]);
          toast.error("Could not load playbooks for this tenant");
        }
      })
      .finally(() => {
        if (!cancelled) setPlaybooksLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveTenantId]);

  useEffect(() => {
    if (!cloneFrom || !effectiveTenantId) return;
    if (playbooksLoading) return;

    let cancelled = false;

    getAlertTypeSchemaById(effectiveTenantId, cloneFrom)
      .then((doc) => {
        if (cancelled) return;
        setExpectedAlertType(doc.alert_type);
        const yaml = buildAlertTypeSchemaYamlFromDocument(doc);
        const safe = doc.alert_type.replace(/[^\w.-]/g, "_");
        setFile(
          new File([yaml], `alert-type-schema-${safe}.yaml`, {
            type: "application/x-yaml",
          }),
        );
        const pid = doc.playbook_id?.trim() ?? "";
        if (pid && playbooksRef.current.some((p) => p.playbook_id === pid)) {
          setPlaybookId(pid);
        }
      })
      .catch(() => {
        if (!cancelled) toast.error("Could not load schema to clone");
      });

    return () => {
      cancelled = true;
    };
  }, [cloneFrom, effectiveTenantId, playbooksLoading]);

  useEffect(() => {
    if (!file) {
      setFileAlertType(null);
      setFileParseError(null);
      return;
    }
    let cancelled = false;
    file
      .text()
      .then((text) => {
        if (cancelled) return;
        const at = extractAlertTypeFromYamlText(text);
        setFileAlertType(at);
        setFileParseError(
          at
            ? null
            : "Could not find a top-level `alert_type` key in the YAML file.",
        );
      })
      .catch(() => {
        if (!cancelled) {
          setFileAlertType(null);
          setFileParseError("Could not read the file (must be UTF-8 text).");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [file]);

  const alertTypeMismatch =
    !!expectedAlertType &&
    !!fileAlertType &&
    expectedAlertType !== fileAlertType;

  const canWrite =
    user?.role === UserRole.PLATFORM_ADMIN ||
    user?.role === UserRole.TENANT_ADMIN;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!effectiveTenantId) {
      toast.error("Choose a tenant");
      return;
    }
    if (!file) {
      toast.error("Choose a .yml or .yaml file");
      return;
    }
    if (alertTypeMismatch) {
      toast.error(
        `This is a new version for "${expectedAlertType}". The uploaded YAML declares "${fileAlertType}" instead — upload a file with the same alert_type or start a new schema.`,
      );
      return;
    }
    if (expectedAlertType && fileParseError) {
      toast.error(fileParseError);
      return;
    }
    setSubmitting(true);
    try {
      const created = await createAlertTypeSchemaFromYaml(
        effectiveTenantId,
        file,
        playbookId || null,
      );
      toast.success(
        `Draft schema ${created.version} saved for ${created.alert_type}. Activate it via the API when ready.`,
      );
      router.push(`/dashboard/${effectiveTenantId}/schema-registry`);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail
          : "Failed to create alert-type schema";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  if (!user) {
    return null;
  }

  if (!canWrite) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Not allowed</h3>
        <p className={PANEL_NOTE}>
          Only tenant administrators or platform admins can upload alert-type
          schemas.
        </p>
        <Link
          href={`/dashboard/${routeTenantId}/schema-registry`}
          className="mt-4 inline-flex h-10 items-center rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90"
        >
          Back to list
        </Link>
      </div>
    );
  }

  if (!isPlatformAdmin && user.tenant_id !== routeTenantId) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Access denied</h3>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          nativeButton={false}
          render={<Link href={`/dashboard/${routeTenantId}/schema-registry`} />}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            New alert-type schema
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {tenantDisplayName === undefined && effectiveTenantId
              ? "…"
              : (tenantDisplayName ?? "Select a tenant")}
            {cloneFrom ? (
              <span className="block text-muted-foreground mt-1">
                Form pre-filled from the cloned version (bump the semver in YAML
                before saving).
                {expectedAlertType ? (
                  <>
                    {" "}
                    Uploaded file must keep{" "}
                    <code className="rounded bg-[#404040] px-1 text-xs">
                      alert_type: {expectedAlertType}
                    </code>
                    .
                  </>
                ) : null}
              </span>
            ) : null}
          </p>
        </div>
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <Upload className="size-4 text-primary" />
          Upload YAML
        </h3>
        <div className="mt-1 space-y-2 text-sm text-muted-foreground">
          <span>
            Choose the tenant and an optional playbook, then upload the
            alert-type schema YAML. The server assigns a new{" "}
            <code className="rounded bg-[#404040] px-1 text-xs">schema_id</code>{" "}
            (UUID); each version is a separate row until you promote one with
            the activate API.
          </span>
          <span className="block text-muted-foreground">
            Required in YAML:{" "}
            <code className="rounded bg-[#404040] px-1 text-xs">
              alert_type
            </code>
            , <code className="rounded bg-[#404040] px-1 text-xs">version</code>{" "}
            (semver),{" "}
            <code className="rounded bg-[#404040] px-1 text-xs">
              field_mapping
            </code>
            ,{" "}
            <code className="rounded bg-[#404040] px-1 text-xs">
              critical_fields
            </code>
            . Optional:{" "}
            <code className="rounded bg-[#404040] px-1 text-xs">
              description
            </code>
            , <code className="rounded bg-[#404040] px-1 text-xs">fields</code>,{" "}
            <code className="rounded bg-[#404040] px-1 text-xs">severity</code>.
          </span>
        </div>
        <form onSubmit={handleSubmit} className="mt-5 space-y-5">
          {/*
            Side by side on wide screens: at full page width a single column of
            selects leaves most of the panel empty.
          */}
          <div className="grid gap-5 lg:grid-cols-2">
            {isPlatformAdmin && (
              <div className="space-y-2">
                <Label className="text-xs text-[#a3a3a3]">Tenant</Label>
                <Select
                  value={selectedTenantId}
                  onValueChange={(v) => {
                    const next = v ?? "";
                    setSelectedTenantId(next);
                    router.replace(`/dashboard/${next}/schema-registry/new`);
                  }}
                >
                  <SelectTrigger className="h-10 w-full min-w-0 bg-[#404040]">
                    <SelectValue placeholder="Select tenant">
                      {(value: string | null) =>
                        value
                          ? (tenants.find((t) => t.tenant_id === value)
                              ?.display_name ??
                            (value === effectiveTenantId
                              ? tenantDisplayName
                              : undefined) ??
                            value)
                          : null
                      }
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {tenants.map((t) => (
                      <SelectItem key={t.tenant_id} value={t.tenant_id}>
                        {t.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="space-y-2">
              <Label className="text-xs text-[#a3a3a3]">
                Playbook (optional)
              </Label>
              <Select
                value={playbookId}
                onValueChange={(v) => setPlaybookId(v ?? "")}
                disabled={!effectiveTenantId || playbooksLoading}
              >
                <SelectTrigger className="h-10 w-full min-w-0 bg-[#404040]">
                  <SelectValue
                    placeholder={
                      !effectiveTenantId
                        ? isPlatformAdmin
                          ? "Select a tenant first"
                          : "Unavailable"
                        : playbooksLoading
                          ? "Loading playbooks…"
                          : "None (optional)"
                    }
                  >
                    {(value: string | null) => {
                      const v = value ?? "";
                      if (v === "") return "None";
                      return (
                        playbooks.find((p) => p.playbook_id === v)
                          ?.playbook_name ?? v
                      );
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None</SelectItem>
                  {playbooks.map((p) => (
                    <SelectItem key={p.playbook_id} value={p.playbook_id}>
                      {p.playbook_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {effectiveTenantId &&
              !playbooksLoading &&
              playbooks.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  This tenant has no playbooks yet; you can still create a
                  schema without one.
                </p>
              ) : null}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ats-file" className="text-xs text-[#a3a3a3]">
              YAML file
            </Label>
            <Input
              id="ats-file"
              type="file"
              accept=".yml,.yaml,application/x-yaml,text/yaml"
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="h-auto cursor-pointer bg-[#404040] py-3"
              aria-invalid={
                alertTypeMismatch || (!!expectedAlertType && !!fileParseError)
              }
              aria-describedby="ats-file-help"
            />
            <div id="ats-file-help" className="space-y-1">
              {alertTypeMismatch ? (
                <p className="text-xs text-destructive">
                  This page is creating a new version for{" "}
                  <code className="rounded bg-[#404040] px-1">
                    {expectedAlertType}
                  </code>
                  , but the uploaded YAML declares{" "}
                  <code className="rounded bg-[#404040] px-1">
                    {fileAlertType}
                  </code>
                  . Upload a file whose top-level{" "}
                  <code className="rounded bg-[#404040] px-1">alert_type</code>{" "}
                  matches, or go back and start a fresh schema instead.
                </p>
              ) : null}
              {!alertTypeMismatch && expectedAlertType && fileParseError ? (
                <p className="text-xs text-destructive">{fileParseError}</p>
              ) : null}
              {!alertTypeMismatch &&
              expectedAlertType &&
              fileAlertType &&
              fileAlertType === expectedAlertType ? (
                <p className="text-xs text-muted-foreground">
                  Alert type matches the source version.
                </p>
              ) : null}
            </div>
          </div>

          <button
            type="submit"
            disabled={
              submitting ||
              !effectiveTenantId ||
              (isPlatformAdmin && !selectedTenantId) ||
              alertTypeMismatch ||
              (!!expectedAlertType && !!fileParseError)
            }
            className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Upload className="size-4" />
            {submitting ? "Creating…" : "Create draft schema"}
          </button>
        </form>
      </div>
    </div>
  );
}
