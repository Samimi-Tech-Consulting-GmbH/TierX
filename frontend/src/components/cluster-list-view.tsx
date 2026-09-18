"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Building2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Layers,
  Search,
  SlidersHorizontal,
} from "lucide-react";

import { ClusterDetailView } from "@/components/cluster-detail-view";
import { Breadcrumbs } from "@/components/dashboard/breadcrumbs";

import { listAllClusters, listClusters } from "@/lib/api";
import { timeAgo } from "@/lib/datetime";
import type { ClusterListItem, PlatformCluster } from "@/lib/types";
import {
  TIME_RANGES,
  TIME_RANGE_ITEMS,
  severityFromValue,
} from "@/lib/alert-display";
import { CLUSTER_STATUS_ITEMS, titleCase } from "@/lib/cluster-display";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PAGE_SIZES } from "@/components/dashboard/pagination";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function createdAfterFor(range: string): string | undefined {
  const hours = TIME_RANGES.find((r) => r.value === range)?.hours;
  if (!hours) return undefined;
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

export function activeClusterId(
  requestedId: string | null,
  visibleIds: string[],
): string | null {
  return requestedId ?? visibleIds[0] ?? null;
}

export function ClusterListView({
  tenantId,
  alertBase,
  homeHref,
}: {
  tenantId: string | null;
  alertBase?: string;
  homeHref: string;
}) {
  const allTenants = tenantId === null;
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedId = searchParams.get("cluster");
  const selectedTenant = searchParams.get("tenant");
  const queryParam = searchParams.get("q") ?? "";
  const [draftQuery, setDraftQuery] = useState(queryParam);

  const [draftStatus, setDraftStatus] = useState("ALL");
  const [draftSince, setDraftSince] = useState("all");
  const [draftPageSize, setDraftPageSize] = useState<number>(PAGE_SIZES[1]);

  const [status, setStatus] = useState("ALL");
  const [since, setSince] = useState("all");
  const [createdAfter, setCreatedAfter] = useState<string | undefined>();

  const [items, setItems] = useState<(ClusterListItem | PlatformCluster)[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[1]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filtersOpen, setFiltersOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDraftQuery(queryParam);
    setPage(0);
  }, [queryParam]);

  const debouncedQuery = useDebouncedValue(draftQuery.trim());
  useEffect(() => {
    if (debouncedQuery === queryParam) return;
    const params = new URLSearchParams(searchParams.toString());
    if (debouncedQuery) params.set("q", debouncedQuery);
    else params.delete("q");
    const next = params.toString();
    router.replace(next ? `?${next}` : "?", { scroll: false });
  }, [debouncedQuery, queryParam, router, searchParams]);

  useEffect(() => {
    if (!filtersOpen) return;
    setDraftStatus(status);
    setDraftSince(since);
    setDraftPageSize(pageSize);
  }, [filtersOpen, pageSize, since, status]);

  useEffect(() => {
    if (!filtersOpen) return;

    const inPortalledPopup = (node: Node | null) =>
      node instanceof Element &&
      node.closest("[data-slot='select-content']") !== null;
    const selectIsOpen = () =>
      document.querySelector("[data-slot='select-content']") !== null;

    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (filterRef.current?.contains(target) || inPortalledPopup(target)) {
        return;
      }
      setFiltersOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !selectIsOpen()) setFiltersOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [filtersOpen]);

  const hasPendingChanges =
    draftStatus !== status ||
    draftSince !== since ||
    draftPageSize !== pageSize;
  const filtersActive = status !== "ALL" || since !== "all";
  const pageCount = Math.max(Math.ceil(total / pageSize), 1);

  function applyFilters() {
    setStatus(draftStatus);
    setSince(draftSince);
    setCreatedAfter(createdAfterFor(draftSince));
    setPageSize(draftPageSize);
    setPage(0);
    setFiltersOpen(false);
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const appliedStatus = queryParam || status === "ALL" ? undefined : status;
    const request =
      tenantId === null
        ? listAllClusters({
            skip: page * pageSize,
            limit: pageSize,
            status: appliedStatus,
            q: queryParam || undefined,
          })
        : listClusters(tenantId, {
            skip: page * pageSize,
            limit: pageSize,
            status: appliedStatus,
            created_after: createdAfter,
            q: queryParam || undefined,
          });
    request
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
      })
      .catch(() => {
        if (!cancelled) {
          setError(
            allTenants
              ? "Could not load clusters across tenants. The platform-wide endpoint may not be available yet."
              : "Failed to load clusters.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [allTenants, tenantId, status, createdAfter, queryParam, page, pageSize]);

  // A bookmarked cluster may not be on the current list page. The detail view
  // fetches it directly, so never replace an explicit query ID with page item 1.
  const activeId = activeClusterId(
    selectedId,
    items.map((item) => item.cluster_id),
  );

  const activeRow = items.find((item) => item.cluster_id === activeId);
  const activeTenantId = allTenants
    ? ((activeRow as PlatformCluster | undefined)?.tenant_id ?? selectedTenant)
    : tenantId;
  const activeAlertBase = allTenants
    ? activeTenantId
      ? `/dashboard/admin/tenants/${activeTenantId}/alerts`
      : null
    : (alertBase ?? null);

  function select(clusterId: string, rowTenantId?: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("cluster", clusterId);
    if (allTenants && rowTenantId) params.set("tenant", rowTenantId);
    router.replace(`?${params.toString()}`, { scroll: false });
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">
            Cluster Analysis
          </h1>
          <p className="mb-4 break-all font-mono text-xs text-muted-foreground">
            {allTenants ? "All tenants" : tenantId}
          </p>
          <p className="text-base text-muted-foreground">
            {allTenants
              ? "Clusters from every tenant, in any status. Selecting one opens it in the tenant that owns it."
              : "Every alert belongs to a cluster. Solo clusters contain one alert; correlated clusters contain related alerts."}
          </p>
        </div>

        <Breadcrumbs
          items={[
            { label: "Home", href: homeHref },
            ...(alertBase
              ? [{ label: "Alerts Management", href: alertBase }]
              : []),
            { label: "Cluster Analysis" },
          ]}
        />
      </div>

      <div className="flex flex-col gap-6 xl:flex-row xl:items-start">
        <div className="rounded-lg bg-card p-4 xl:w-[340px] xl:shrink-0">
          <div className="flex items-center gap-2 px-2 pb-4">
            <h2 className="text-lg font-bold text-foreground">
              Threat Clusters
            </h2>
            {!loading && !error && (
              <span className="text-sm text-muted-foreground">
                {total.toLocaleString("en-US")}
              </span>
            )}

            <div className="relative ml-auto" ref={filterRef}>
              <button
                type="button"
                onClick={() => setFiltersOpen((open) => !open)}
                aria-expanded={filtersOpen}
                className={cn(
                  "flex h-8 items-center gap-2 rounded-md px-3 text-sm transition-colors",
                  filtersActive
                    ? "bg-primary text-primary-foreground"
                    : "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]",
                )}
              >
                <SlidersHorizontal className="size-3.5" />
                Filter
              </button>

              {filtersOpen && (
                <div className="absolute right-0 top-10 z-20 w-[260px] space-y-4 rounded-lg border border-[#404040] bg-card p-4 shadow-lg">
                  <label className="block space-y-2">
                    <span className="text-xs text-muted-foreground">
                      Status
                    </span>
                    <Select
                      items={CLUSTER_STATUS_ITEMS}
                      value={draftStatus}
                      onValueChange={(v) => setDraftStatus(v ?? "ALL")}
                    >
                      <SelectTrigger className="h-9 w-full bg-[#404040]">
                        <SelectValue placeholder="All statuses" />
                      </SelectTrigger>
                      <SelectContent>
                        {CLUSTER_STATUS_ITEMS.map((item) => (
                          <SelectItem key={item.value} value={item.value}>
                            {item.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>

                  <label className="block space-y-2">
                    <span className="text-xs text-muted-foreground">
                      Period
                    </span>
                    <Select
                      items={TIME_RANGE_ITEMS}
                      value={draftSince}
                      onValueChange={(v) => setDraftSince(v ?? "all")}
                      disabled={allTenants}
                    >
                      <SelectTrigger
                        className="h-9 w-full bg-[#404040]"
                        title={
                          allTenants
                            ? "Not available across tenants yet — the platform endpoint has no time filter"
                            : undefined
                        }
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TIME_RANGES.map((range) => (
                          <SelectItem key={range.value} value={range.value}>
                            {range.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="block space-y-2">
                    <span className="text-xs text-muted-foreground">
                      Per page
                    </span>
                    <Select
                      value={String(draftPageSize)}
                      onValueChange={(v) =>
                        setDraftPageSize(Number(v ?? PAGE_SIZES[1]))
                      }
                    >
                      <SelectTrigger className="h-9 w-full bg-[#404040]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PAGE_SIZES.map((size) => (
                          <SelectItem key={size} value={String(size)}>
                            {size}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>

                  <button
                    type="button"
                    onClick={applyFilters}
                    className={cn(
                      "h-9 w-full rounded-md bg-primary text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90",
                      !hasPendingChanges && "opacity-60",
                    )}
                  >
                    Apply filters
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* The icon centres on the input, so the padding sits outside it. */}
          <div className="px-2 pb-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="h-9 bg-[#404040] pl-9"
                placeholder="Search cluster id or summary…"
                value={draftQuery}
                onChange={(event) => setDraftQuery(event.target.value)}
                autoComplete="off"
              />
            </div>
          </div>

          {loading ? (
            <div className="max-h-[610px] space-y-3 overflow-y-auto pr-1">
              {Array.from({ length: 5 }).map((_, index) => (
                <div
                  key={index}
                  className="h-[110px] animate-pulse rounded-lg bg-white/5"
                />
              ))}
            </div>
          ) : error && items.length === 0 ? (
            <p className="p-10 text-center text-sm text-destructive">{error}</p>
          ) : items.length === 0 ? (
            <p className="p-10 text-center text-sm text-muted-foreground">
              No clusters have been created.
            </p>
          ) : (
            <div className="max-h-[610px] space-y-3 overflow-y-auto pr-1">
              {items.map((cluster) => {
                const severity = severityFromValue(cluster.severity.max);
                const grouping =
                  cluster.clustering_status ??
                  (cluster.alert_count > 1
                    ? "CORRELATED"
                    : cluster.requested_analysis_version > 0
                      ? "SOLO_CLUSTER"
                      : "DEBOUNCING");
                const active = cluster.cluster_id === activeId;
                const owner = (cluster as PlatformCluster).tenant_name ?? null;
                return (
                  <button
                    key={cluster.cluster_id}
                    type="button"
                    onClick={() =>
                      select(
                        cluster.cluster_id,
                        (cluster as PlatformCluster).tenant_id,
                      )
                    }
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full flex-col gap-2 rounded-lg border p-4 text-left transition-colors",
                      active
                        ? "border-[#d60c89] bg-[#d60c89]/20"
                        : "border-transparent bg-[#404040] hover:bg-[#4a4a4a]",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "shrink-0 text-xs font-bold",
                          severity.className,
                        )}
                      >
                        {severity.label}
                      </span>
                      <span className="min-w-0 flex-1 truncate font-mono text-sm font-bold text-foreground">
                        {cluster.cluster_id}
                      </span>
                      <span className="shrink-0 text-xs text-[#a3a3a3]">
                        {cluster.alert_count} alert
                        {cluster.alert_count === 1 ? "" : "s"}
                      </span>
                    </div>

                    <p className="line-clamp-2 text-sm text-[#d4d4d4]">
                      {cluster.summary?.headline ?? "—"}
                    </p>

                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#a3a3a3]">
                      <span className="inline-flex items-center gap-1.5">
                        <Clock className="size-3 text-[#737373]" />
                        {timeAgo(new Date(cluster.last_seen))}
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <Layers className="size-3 text-[#737373]" />
                        {titleCase(grouping)}
                      </span>
                      {allTenants && owner ? (
                        <span className="inline-flex min-w-0 items-center gap-1.5">
                          <Building2 className="size-3 shrink-0 text-[#737373]" />
                          <span className="truncate">{owner}</span>
                        </span>
                      ) : null}
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          {!loading && !error && pageCount > 1 && (
            <div className="mt-4 flex items-center justify-between gap-2 border-t border-[#404040] px-2 pt-3">
              <button
                type="button"
                onClick={() => setPage(Math.max(page - 1, 0))}
                disabled={page === 0}
                aria-label="Previous page"
                className="flex size-8 items-center justify-center rounded-md bg-[#404040] text-[#d4d4d4] transition-colors hover:bg-[#4a4a4a] disabled:opacity-40"
              >
                <ChevronLeft className="size-4" />
              </button>
              <span className="text-xs text-muted-foreground">
                Page {page + 1} of {pageCount}
              </span>
              <button
                type="button"
                onClick={() => setPage(Math.min(page + 1, pageCount - 1))}
                disabled={page >= pageCount - 1}
                aria-label="Next page"
                className="flex size-8 items-center justify-center rounded-md bg-[#404040] text-[#d4d4d4] transition-colors hover:bg-[#4a4a4a] disabled:opacity-40"
              >
                <ChevronRight className="size-4" />
              </button>
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          {activeId && activeTenantId && activeAlertBase ? (
            <ClusterDetailView
              key={`${activeTenantId}:${activeId}`}
              tenantId={activeTenantId}
              clusterId={activeId}
              alertBase={activeAlertBase}
            />
          ) : (
            !loading && (
              <p className="rounded-lg bg-card p-10 text-center text-sm text-muted-foreground">
                Select a cluster to see its analysis.
              </p>
            )
          )}
        </div>
      </div>

      {error && items.length > 0 && (
        <p className="text-sm text-destructive">{error}</p>
      )}
    </div>
  );
}
