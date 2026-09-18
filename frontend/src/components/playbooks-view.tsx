"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Filter,
  Loader2,
  PlayCircle,
  Search,
  Tags,
} from "lucide-react";
import { toast } from "sonner";

import {
  getMyTenant,
  getPlatformPlaybookStats,
  getPlaybookStats,
  listAllPlaybooks,
  listPlaybooks,
} from "@/lib/api";
import type {
  PlaybookListItem,
  PlaybookStats,
  PlatformPlaybook,
} from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatLocaleDateTime } from "@/lib/datetime";
import { PANEL, PANEL_NOTE, PANEL_TITLE, PILL } from "@/lib/cluster-display";
import { PlaybookDetailView } from "@/components/playbook-detail-view";
import { StatCard } from "@/components/dashboard/stat-card";
import { PAGE_SIZES } from "@/components/dashboard/pagination";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type StatusFilter = "all" | "active" | "inactive";

const STATUS_ITEMS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active only" },
  { value: "inactive", label: "Inactive only" },
];

const FETCH_LIMIT = 500;

export function PlaybooksView({ tenantId }: { tenantId: string | null }) {
  const allTenants = tenantId === null;
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();

  const [items, setItems] = useState<(PlaybookListItem | PlatformPlaybook)[]>(
    [],
  );
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const pageSize = PAGE_SIZES[1];
  const [tenantDisplayName, setTenantDisplayName] = useState<string | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<PlaybookStats | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [draftStatus, setDraftStatus] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);

  const selectedPlaybookId = searchParams.get("playbook");
  const appliedQuery = useDebouncedValue(query.trim());

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

  const serverPage = allTenants ? page : 0;
  const serverQuery = allTenants ? appliedQuery : "";
  const serverStatus = allTenants ? status : "all";

  const load = useCallback(async () => {
    if (tenantId === null) {
      const pack = await listAllPlaybooks({
        skip: serverPage * pageSize,
        limit: pageSize,
        q: serverQuery || undefined,
        is_active:
          serverQuery || serverStatus === "all"
            ? undefined
            : serverStatus === "active",
      });
      setItems(pack.items);
      setTotal(pack.total);
      return;
    }
    const rows = await listPlaybooks(tenantId, { limit: FETCH_LIMIT });
    setItems(rows);
    setTotal(rows.length);
  }, [tenantId, serverPage, pageSize, serverQuery, serverStatus]);

  const loadStats = useCallback(async () => {
    setStatsError(null);
    try {
      setStats(
        tenantId === null
          ? await getPlatformPlaybookStats()
          : await getPlaybookStats(tenantId),
      );
    } catch {
      setStats(null);
      setStatsError("Could not load playbook metrics.");
    }
  }, [tenantId]);

  const refresh = useCallback(
    () => Promise.all([load(), loadStats()]).then(() => undefined),
    [load, loadStats],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      load(),
      loadStats(),
      tenantId === null ? null : getMyTenant(tenantId).catch(() => null),
    ])
      .then(([, , tenant]) => {
        if (cancelled) return;
        setTenantDisplayName(tenant?.display_name ?? null);
      })
      .catch(() => {
        if (!cancelled) toast.error("Failed to load playbooks");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load, loadStats, tenantId]);

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

  function applyFilters() {
    setStatus(draftStatus);
    setFiltersOpen(false);
    setPage(0);
  }

  const searchTerm = query.trim().toLowerCase();
  const searching = allTenants
    ? appliedQuery.length > 0
    : searchTerm.length > 0;

  const filtered = useMemo(() => {
    if (allTenants) return items;
    return items
      .filter((p) => {
        if (!searching) {
          if (status === "active" && !p.is_active) return false;
          if (status === "inactive" && p.is_active) return false;
          return true;
        }
        return (
          p.playbook_name.toLowerCase().includes(searchTerm) ||
          (p.alert_types ?? []).some((t) =>
            t.toLowerCase().includes(searchTerm),
          )
        );
      })
      .sort((a, b) => {
        if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
        return a.playbook_name.localeCompare(b.playbook_name);
      });
  }, [allTenants, items, searching, searchTerm, status]);

  const pageCount = Math.max(Math.ceil(total / pageSize), 1);

  const activePlaybookId =
    selectedPlaybookId &&
    filtered.some((p) => p.playbook_id === selectedPlaybookId)
      ? selectedPlaybookId
      : (filtered[0]?.playbook_id ?? null);

  const activeRow = filtered.find((p) => p.playbook_id === activePlaybookId);
  const activeTenantId = allTenants ? (activeRow?.tenant_id ?? null) : tenantId;

  function selectPlaybook(playbookId: string) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("playbook", playbookId);
    router.replace(`?${next.toString()}`, { scroll: false });
  }

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
          You can only view playbooks for your own tenant.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading playbooks…
      </div>
    );
  }

  return (
    <div className="space-y-6">
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
              Playbook Management
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {(() => {
                const owner = allTenants
                  ? "All tenants"
                  : (tenantDisplayName ?? tenantId);
                const count = allTenants ? total : filtered.length;
                if (searching) {
                  return `${owner} · ${count} match${count === 1 ? "" : "es"}`;
                }
                return allTenants
                  ? `${owner} · ${count} playbook${count === 1 ? "" : "s"} across the platform`
                  : `${owner} · analysis playbooks stored in this tenant's database`;
              })()}
            </p>
          </div>
        </div>
        {canWrite && !allTenants ? (
          <Link
            href={`/dashboard/${tenantId}/playbooks/new`}
            className="inline-flex h-10 shrink-0 items-center rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90"
          >
            New playbook
          </Link>
        ) : null}
      </div>

      <div className="space-y-2">
        <div className="grid gap-4 md:grid-cols-3">
          <StatCard
            label="Active playbooks"
            value={stats ? `${stats.active_playbooks}` : "–"}
            hint={stats ? `of ${stats.total_playbooks} stored` : "Unavailable"}
            icon={<PlayCircle className="size-5 text-[#4ade80]" />}
            iconClass="bg-[#16a34a]/20"
          />
          <StatCard
            label="Alert types covered"
            value={stats ? `${stats.covered_alert_types}` : "–"}
            hint={
              stats?.covered_alert_types === 0
                ? "no routing labels set"
                : "distinct routing labels"
            }
            icon={<Tags className="size-5 text-[#60a5fa]" />}
            iconClass="bg-[#2563eb]/20"
          />
          <StatCard
            label="System playbooks"
            value={stats ? `${stats.system_playbooks}` : "–"}
            hint="platform-managed defaults"
            icon={<BookOpen className="size-5 text-[#fbbf24]" />}
            iconClass="bg-[#d97706]/20"
          />
        </div>
        {statsError ? (
          <p className="text-xs text-destructive">{statsError}</p>
        ) : null}
      </div>

      <div className="grid gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <div className={cn(PANEL, "h-fit")}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <h3 className={PANEL_TITLE}>
                <BookOpen className="size-4 text-primary" />
                Playbooks
              </h3>
              {/*
               * Across tenants this is the server's total for the current
               * filters, not the length of the page on screen — the same
               * number the cluster list shows beside its title.
               */}
              {loading ? null : (
                <span className="text-sm text-muted-foreground">
                  {(allTenants ? total : filtered.length).toLocaleString(
                    "en-US",
                  )}
                </span>
              )}
            </div>
            <div className="relative" ref={filterRef}>
              <button
                type="button"
                onClick={() => setFiltersOpen((open) => !open)}
                aria-expanded={filtersOpen}
                aria-label="Filter playbooks"
                disabled={searching}
                title={searching ? "Search covers every status" : undefined}
                className={cn(
                  "flex size-8 items-center justify-center rounded-md transition-colors",
                  status !== "all" && !searching
                    ? "bg-primary text-primary-foreground"
                    : "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]",
                  searching && "cursor-not-allowed opacity-50",
                )}
              >
                {/* Single closed path, so filling it gives the solid funnel. */}
                <Filter className="size-3.5" fill="currentColor" />
              </button>

              {filtersOpen && (
                <div className="absolute right-0 top-10 z-20 w-[240px] space-y-4 rounded-lg border border-[#404040] bg-card p-4 shadow-lg">
                  <label className="block space-y-2">
                    <span className="text-xs text-muted-foreground">
                      Status
                    </span>
                    <Select
                      items={STATUS_ITEMS}
                      value={draftStatus}
                      onValueChange={(v) =>
                        setDraftStatus((v as StatusFilter) ?? "all")
                      }
                    >
                      <SelectTrigger className="h-9 w-full bg-[#404040]">
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
                  </label>

                  <button
                    type="button"
                    onClick={applyFilters}
                    className={cn(
                      "h-9 w-full rounded-md bg-primary text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90",
                      draftStatus === status && "opacity-60",
                    )}
                  >
                    Apply filters
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* The icon centres on the input, so the padding sits outside it. */}
          <div className="mt-4 pb-4">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="h-10 bg-[#404040] pl-9"
                placeholder="Search playbooks…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(0);
                }}
                autoComplete="off"
              />
            </div>
          </div>

          <div className="space-y-2 border-t border-white/5 pt-4">
            {filtered.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground">
                {items.length === 0 ? "No playbooks yet." : "No matches."}
                {items.length === 0 && canWrite && !allTenants ? (
                  <>
                    {" "}
                    <Link
                      href={`/dashboard/${tenantId}/playbooks/new`}
                      className="font-bold text-primary underline-offset-4 hover:underline"
                    >
                      Upload YAML
                    </Link>
                  </>
                ) : null}
              </p>
            ) : (
              filtered.map((p) => {
                const selected = p.playbook_id === activePlaybookId;
                return (
                  <button
                    key={p.playbook_id}
                    type="button"
                    onClick={() => selectPlaybook(p.playbook_id)}
                    aria-current={selected ? "true" : undefined}
                    className={cn(
                      "w-full rounded-lg p-4 text-left transition-colors",
                      selected
                        ? "border border-primary bg-primary/20"
                        : "border border-transparent bg-[#404040]/50 hover:bg-[#404040]",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "size-2 shrink-0 rounded-full",
                          p.is_active ? "bg-[#16a34a]" : "bg-[#737373]",
                        )}
                      />
                      <span className="truncate text-sm font-bold text-foreground">
                        {p.playbook_name}
                      </span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                        v{p.version}
                      </span>
                    </div>
                    <p className="mt-2 truncate text-xs text-muted-foreground">
                      {(p.alert_types ?? []).length > 0
                        ? (p.alert_types ?? []).join(", ")
                        : "No alert types — not routed by label"}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                      <span
                        className={cn(
                          PILL,
                          "px-2 py-0.5",
                          p.is_active ? "bg-[#16a34a]" : "bg-[#525252]",
                        )}
                      >
                        {p.is_active ? "Active" : "Inactive"}
                      </span>
                      {p.is_system ? (
                        <span className={cn(PILL, "bg-[#525252] px-2 py-0.5")}>
                          System
                        </span>
                      ) : null}
                      <span className="text-[#737373]">
                        {formatLocaleDateTime(p.updated_at)}
                      </span>
                      {allTenants ? (
                        <span className="w-full truncate text-[#a3a3a3]">
                          {(p as PlatformPlaybook).tenant_name ?? p.tenant_id}
                        </span>
                      ) : null}
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {allTenants && !loading && pageCount > 1 ? (
            <div className="mt-4 flex items-center justify-between gap-2 border-t border-white/5 pt-4">
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
          ) : null}
        </div>

        {activePlaybookId && activeTenantId ? (
          <PlaybookDetailView
            key={`${activeTenantId}:${activePlaybookId}`}
            tenantId={activeTenantId}
            playbookId={activePlaybookId}
            canWrite={canWrite}
            onChanged={() => void refresh()}
          />
        ) : (
          <div className={cn(PANEL, "flex items-center justify-center")}>
            <p className="text-sm text-muted-foreground">
              Select a playbook to see its workflow.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
