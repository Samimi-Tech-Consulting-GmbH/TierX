"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, FileCode2, Loader2, Search } from "lucide-react";
import { toast } from "sonner";

import {
  getMyTenant,
  listAlertTypeSchemas,
  listAllAlertTypeSchemas,
  activateAlertTypeSchema,
  ApiError,
} from "@/lib/api";
import type { AlertTypeSchemaDocument, PlatformSchema } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatLocaleDateTime } from "@/lib/datetime";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
  TABLE_HEAD,
  TABLE_ROW,
} from "@/lib/cluster-display";
import {
  PAGE_SIZES,
  TablePaginationFooter,
} from "@/components/dashboard/pagination";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import {
  SchemaCriticalFieldsPanel,
  SchemaDetailRail,
  useSchemaDetail,
} from "@/components/schema-detail-view";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type StatusFilter = "all" | "active" | "draft";

const STATUS_ITEMS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active only" },
  { value: "draft", label: "Draft only" },
];

function schemaFieldCount(s: AlertTypeSchemaDocument): number {
  const map =
    s.field_mapping && typeof s.field_mapping === "object"
      ? (s.field_mapping as Record<string, string>)
      : {};
  const mapped = Object.keys(map).length;
  const extra = Array.isArray(s.fields) ? s.fields.length : 0;
  return mapped + extra;
}

export function SchemaRegistryView({ tenantId }: { tenantId: string | null }) {
  const allTenants = tenantId === null;
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  const [items, setItems] = useState<
    (AlertTypeSchemaDocument | PlatformSchema)[]
  >([]);
  const [total, setTotal] = useState(0);
  const selectedSchemaId = searchParams.get("schema");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[1]);
  const [tenantDisplayName, setTenantDisplayName] = useState<string | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [activatingSchemaId, setActivatingSchemaId] = useState<string | null>(
    null,
  );
  const [draftStatus, setDraftStatus] = useState<StatusFilter>("all");

  const [activeFilter, setActiveFilter] = useState<StatusFilter>("all");
  const [searchInput, setSearchInput] = useState("");
  const appliedQ = useDebouncedValue(searchInput.trim());

  const canWrite =
    user?.role === UserRole.PLATFORM_ADMIN ||
    user?.role === UserRole.TENANT_ADMIN;

  const backHref = allTenants
    ? "/dashboard/admin"
    : user?.role === UserRole.PLATFORM_ADMIN
      ? `/dashboard/admin/tenants/${tenantId}`
      : user?.tenant_id
        ? `/dashboard/${user.tenant_id}`
        : "/login";

  const searching = appliedQ.length > 0;
  const statusFilterSuppressed = searching && allTenants;
  const filtersApplied = activeFilter !== "all" || searching;

  const hasPendingChanges = draftStatus !== activeFilter;

  const activeSchemaId =
    selectedSchemaId && items.some((s) => s.schema_id === selectedSchemaId)
      ? selectedSchemaId
      : (items[0]?.schema_id ?? null);

  const ownerOf = (
    s: AlertTypeSchemaDocument | PlatformSchema,
  ): string | null =>
    allTenants ? ((s as PlatformSchema).tenant_id ?? null) : tenantId;

  const activeSchema = items.find((s) => s.schema_id === activeSchemaId);
  const activeTenantId = activeSchema ? ownerOf(activeSchema) : null;

  function selectSchema(schemaId: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("schema", schemaId);
    router.replace(`?${params.toString()}`, { scroll: false });
  }

  function applyFilters() {
    setActiveFilter(draftStatus);
    setPage(0);
  }

  useEffect(() => {
    if (tenantId === null) return;
    let cancelled = false;
    getMyTenant(tenantId)
      .then((tenant) => {
        if (!cancelled) setTenantDisplayName(tenant?.display_name ?? null);
      })
      .catch(() => {
        if (!cancelled) setTenantDisplayName(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const queryFor = useCallback(
    () => ({
      skip: page * pageSize,
      limit: pageSize,
      is_active:
        statusFilterSuppressed || activeFilter === "all"
          ? undefined
          : activeFilter === "active",
      q: appliedQ || undefined,
    }),
    [activeFilter, appliedQ, page, pageSize, statusFilterSuppressed],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (tenantId === null
      ? listAllAlertTypeSchemas(queryFor())
      : listAlertTypeSchemas(tenantId, queryFor())
    )
      .then((pack) => {
        if (cancelled) return;
        setItems(pack.items);
        setTotal(pack.total);
      })
      .catch(() => {
        if (!cancelled) toast.error("Failed to load schemas");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, queryFor]);

  async function refreshSchemas() {
    const pack =
      tenantId === null
        ? await listAllAlertTypeSchemas(queryFor())
        : await listAlertTypeSchemas(tenantId, queryFor());
    setItems(pack.items);
    setTotal(pack.total);
  }

  async function handleActivate(s: AlertTypeSchemaDocument | PlatformSchema) {
    const owner = ownerOf(s);
    if (!canWrite || s.is_active || !owner) return;
    setActivatingSchemaId(s.schema_id);
    try {
      await activateAlertTypeSchema(owner, s.alert_type, s.schema_id);
      toast.success(`Version ${s.version} is now active for ${s.alert_type}.`);
      await refreshSchemas();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detail : "Activation failed");
    } finally {
      setActivatingSchemaId(null);
    }
  }

  const detail = useSchemaDetail({
    tenantId: activeTenantId ?? "",
    schemaId: activeTenantId ? activeSchemaId : null,
    canWrite,
    onChanged: () => void refreshSchemas(),
  });

  function accessDenied(): boolean {
    if (!user) return true;
    if (user.role === UserRole.PLATFORM_ADMIN) return false;
    return allTenants || user.tenant_id !== tenantId;
  }

  if (accessDenied()) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Access denied</h3>
        <p className={PANEL_NOTE}>
          You can only view schemas for your own tenant.
        </p>
      </div>
    );
  }

  if (loading && items.length === 0 && !filtersApplied) {
    return (
      <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading schemas…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <Button
                variant="ghost"
                size="icon"
                nativeButton={false}
                render={<Link href={backHref} />}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <div>
                <h1 className="text-3xl font-bold tracking-tight">
                  Schema Registry
                </h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  {`${allTenants ? "All tenants" : (tenantDisplayName ?? tenantId)} · ${total} ${
                    searching
                      ? `match${total === 1 ? "" : "es"}`
                      : `schema${total === 1 ? "" : "s"}`
                  }`}
                </p>
              </div>
            </div>
            {canWrite && !allTenants ? (
              <Link
                href={`/dashboard/${tenantId}/schema-registry/new`}
                className="inline-flex h-10 shrink-0 items-center rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90"
              >
                New schema
              </Link>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-4 rounded-lg bg-card px-6 py-4">
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">Status:</span>
              <Select
                items={STATUS_ITEMS}
                value={statusFilterSuppressed ? "all" : draftStatus}
                onValueChange={(v) =>
                  setDraftStatus((v as StatusFilter) ?? "all")
                }
                disabled={statusFilterSuppressed}
              >
                <SelectTrigger
                  aria-label="Status"
                  className="h-10 w-[160px] bg-[#404040] disabled:opacity-60"
                  title={
                    statusFilterSuppressed
                      ? "Search covers every status across tenants"
                      : undefined
                  }
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_ITEMS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="schema-search"
                className="h-10 bg-[#404040] pl-9"
                placeholder="Search alert type (e.g. phishing, malware)"
                value={searchInput}
                onChange={(e) => {
                  setSearchInput(e.target.value);
                  setPage(0);
                }}
                autoComplete="off"
              />
            </div>

            <div className="flex items-center gap-4">
              <span className="text-sm text-muted-foreground">
                {total.toLocaleString("en-US")}{" "}
                {filtersApplied
                  ? `match${total === 1 ? "" : "es"}`
                  : `schema${total === 1 ? "" : "s"}`}
              </span>
              <button
                type="button"
                onClick={applyFilters}
                className={cn(
                  "h-10 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90",
                  !hasPendingChanges && "opacity-60",
                )}
              >
                Apply filters
              </button>
            </div>
          </div>

          <div className={PANEL}>
            <h3 className={PANEL_TITLE}>
              <FileCode2 className="size-4 text-primary" />
              Registry
            </h3>
            <p className={PANEL_NOTE}>
              {searching
                ? allTenants
                  ? "Search covers every status in every tenant."
                  : "Search can be combined with the status filter and covers this tenant only. Switch tenant in the sidebar to search another one."
                : "Draft and active versions live in the tenant database. Promoting a draft with Activate deactivates any other active version of the same alert type."}
            </p>

            <div className="mt-4">
              {loading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <div
                      key={index}
                      className="h-10 w-full animate-pulse rounded bg-white/5"
                    />
                  ))}
                </div>
              ) : items.length === 0 ? (
                <p className="p-10 text-center text-sm text-muted-foreground">
                  {filtersApplied
                    ? "No schemas match your filters."
                    : "No schemas yet."}
                  {!filtersApplied && canWrite && !allTenants ? (
                    <>
                      {" "}
                      <Link
                        href={`/dashboard/${tenantId}/schema-registry/new`}
                        className="font-bold text-primary underline-offset-4 hover:underline"
                      >
                        Upload YAML
                      </Link>
                    </>
                  ) : null}
                </p>
              ) : (
                <div className="overflow-x-auto rounded-lg">
                  <table className="w-full min-w-[720px] text-left">
                    <thead className={TABLE_HEAD}>
                      <tr>
                        <th className="px-4 py-3">Alert type</th>
                        <th className="px-4 py-3">Version</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3 text-right">Fields</th>
                        <th className="px-4 py-3 text-right">Critical</th>
                        {allTenants ? (
                          <th className="max-w-[200px] px-4 py-3">Tenant</th>
                        ) : null}
                        <th className="px-4 py-3">Last updated</th>
                        <th className="w-28 px-4 py-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((s) => (
                        <tr
                          key={s.schema_id}
                          onClick={() => selectSchema(s.schema_id)}
                          aria-current={
                            s.schema_id === activeSchemaId ? "true" : undefined
                          }
                          className={cn(
                            "cursor-pointer transition-colors",
                            TABLE_ROW,
                            s.schema_id === activeSchemaId
                              ? "bg-primary/10"
                              : "hover:bg-white/5",
                          )}
                        >
                          <td className="max-w-[280px] px-4 py-3">
                            <span
                              className="block truncate font-mono text-xs text-[#d4d4d4]"
                              title={s.alert_type}
                            >
                              {s.alert_type}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm font-bold tabular-nums text-foreground">
                            v{s.version}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={cn(
                                PILL,
                                s.is_active ? "bg-[#16a34a]" : "bg-[#525252]",
                              )}
                            >
                              {s.is_active ? "Active" : "Draft"}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-sm tabular-nums text-muted-foreground">
                            {schemaFieldCount(s)}
                          </td>
                          <td className="px-4 py-3 text-right text-sm tabular-nums text-muted-foreground">
                            {Array.isArray(s.critical_fields)
                              ? s.critical_fields.length
                              : 0}
                          </td>
                          {allTenants ? (
                            <td className="max-w-[200px] px-4 py-3">
                              <span className="block truncate text-sm text-muted-foreground">
                                {(s as PlatformSchema).tenant_name ??
                                  (s as PlatformSchema).tenant_id ??
                                  "—"}
                              </span>
                            </td>
                          ) : null}
                          <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                            {formatLocaleDateTime(s.updated_at)}
                          </td>
                          <td
                            className="px-4 py-3 text-right"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {canWrite && !s.is_active ? (
                              <button
                                type="button"
                                disabled={activatingSchemaId === s.schema_id}
                                onClick={() => void handleActivate(s)}
                                className="h-8 rounded-md bg-[#404040] px-3 text-xs font-bold text-foreground transition-colors hover:bg-[#4a4a4a] disabled:opacity-40"
                              >
                                {activatingSchemaId === s.schema_id
                                  ? "Activating…"
                                  : "Activate"}
                              </button>
                            ) : (
                              <span className="text-sm text-muted-foreground">
                                —
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {!loading && (
            <TablePaginationFooter
              page={page}
              pageSize={pageSize}
              total={total}
              onPageChange={setPage}
              onPageSizeChange={(size) => {
                setPageSize(size);
                setPage(0);
              }}
            />
          )}

          {activeSchemaId ? (
            <SchemaCriticalFieldsPanel detail={detail} />
          ) : null}
        </div>

        {activeSchemaId ? (
          <SchemaDetailRail detail={detail} />
        ) : (
          <div className={cn(PANEL, "text-center")}>
            <p className="text-sm text-muted-foreground">
              Select a schema to see its details, fields and versions.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
