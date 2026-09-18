"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Plus, Search } from "lucide-react";
import { toast } from "sonner";

import { listTenants, ApiError } from "@/lib/api";
import type { TenantDocument } from "@/lib/types";
import { TenantStatus } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CreateTenantModal } from "@/components/admin/create-tenant-modal";
import { TenantListStatusControl } from "@/components/admin/tenant-list-status-control";
import { formatLocaleDateTime } from "@/lib/datetime";
import { TABLE_HEAD, TABLE_ROW } from "@/lib/cluster-display";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

const STATUS_ITEMS = [
  { value: "ALL", label: "All statuses" },
  ...Object.values(TenantStatus).map((s) => ({ value: s, label: s })),
];

export default function AdminTenantsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [tenants, setTenants] = useState<TenantDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const [draftSearch, setDraftSearch] = useState("");
  const [draftStatus, setDraftStatus] = useState<string>("ALL");

  const settledSearch = useDebouncedValue(draftSearch);
  useEffect(() => {
    setSearch(settledSearch);
  }, [settledSearch]);

  const hasPendingChanges = draftStatus !== statusFilter;

  function applyFilters() {
    setStatusFilter(draftStatus);
  }
  const [createOpen, setCreateOpen] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [menuOpenFor, setMenuOpenFor] = useState<string | null>(null);

  useEffect(() => {
    if (!highlightId) return;
    const t = setTimeout(() => setHighlightId(null), 8000);
    return () => clearTimeout(t);
  }, [highlightId]);

  const fetchTenants = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listTenants({
        search: search || undefined,
        status:
          statusFilter !== "ALL" ? (statusFilter as TenantStatus) : undefined,
      });
      setTenants(data);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403 && user?.tenant_id) {
        toast.error("You do not have permission to access this page");
        router.replace(`/dashboard/${user.tenant_id}`);
        return;
      }
      if (e instanceof ApiError) {
        setLoadError(e.detail);
      } else {
        setLoadError(
          "We could not reach the server. Check your connection and try again.",
        );
      }
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, router, user?.tenant_id]);

  useEffect(() => {
    void fetchTenants();
  }, [fetchTenants]);

  function mergeTenant(updated: TenantDocument) {
    setTenants((prev) =>
      prev.map((x) => (x.tenant_id === updated.tenant_id ? updated : x)),
    );
  }

  if (loadError && !loading && tenants.length === 0) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 text-center">
        <p className="text-muted-foreground max-w-md">{loadError}</p>
        <Button onClick={() => void fetchTenants()}>Retry</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">
            Tenant Management
          </h1>
          <p className="text-base text-muted-foreground">
            Platform administration — all organizations on TierX.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90"
        >
          <Plus className="size-4" />
          New Tenant
        </button>
      </div>

      <CreateTenantModal
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(t) => {
          setHighlightId(t.tenant_id);
          void fetchTenants();
        }}
      />

      <div className="flex flex-wrap items-center gap-4 rounded-lg bg-card px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">Status:</span>
          <Select
            items={STATUS_ITEMS}
            value={draftStatus}
            onValueChange={(v) => setDraftStatus(v ?? "ALL")}
          >
            <SelectTrigger className="h-10 w-[180px] bg-[#404040]">
              <SelectValue placeholder="All statuses" />
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
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search slug or display name…"
            value={draftSearch}
            onChange={(e) => setDraftSearch(e.target.value)}
            className="h-10 bg-[#404040] pl-9"
          />
        </div>

        <div className="flex items-center gap-4">
          {!loading && (
            <span className="text-sm text-muted-foreground">
              {tenants.length} tenant{tenants.length === 1 ? "" : "s"}
            </span>
          )}
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

      <div className="overflow-hidden rounded-lg bg-card">
        {loading ? (
          <div className="space-y-3 p-6">
            {Array.from({ length: 5 }).map((_, index) => (
              <div
                key={index}
                className="h-10 w-full animate-pulse rounded bg-white/5"
              />
            ))}
          </div>
        ) : tenants.length === 0 ? (
          <p className="p-10 text-center text-sm text-muted-foreground">
            No tenants match your filters.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-left">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className="px-6 py-4">Display name</th>
                  <th className="px-6 py-4">Name (slug)</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Sources</th>
                  <th className="px-6 py-4">Contact</th>
                  <th className="px-6 py-4">Created</th>
                  <th className="w-24 px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((tenant) => (
                  <tr
                    key={tenant.tenant_id}
                    onClick={() =>
                      router.push(
                        `/dashboard/admin/tenants/${tenant.tenant_id}`,
                      )
                    }
                    className={cn(
                      "cursor-pointer transition-colors",
                      TABLE_ROW,
                      highlightId === tenant.tenant_id
                        ? "bg-primary/10"
                        : "hover:bg-white/5",
                    )}
                  >
                    <td className="px-6 py-4 text-sm font-medium text-foreground">
                      {tenant.display_name}
                    </td>
                    <td className="px-6 py-4 font-mono text-sm text-muted-foreground">
                      {tenant.name}
                    </td>
                    <td
                      className="px-6 py-4"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <TenantListStatusControl
                        tenant={tenant}
                        menuOpen={menuOpenFor === tenant.tenant_id}
                        onMenuOpenChange={(open) =>
                          setMenuOpenFor(open ? tenant.tenant_id : null)
                        }
                        onTenantUpdated={mergeTenant}
                      />
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap gap-1.5">
                        {(tenant.allowed_source_systems ?? []).length === 0 ? (
                          <span className="text-sm text-muted-foreground">
                            —
                          </span>
                        ) : (
                          tenant.allowed_source_systems.map((source) => (
                            <span
                              key={source}
                              className="rounded-md bg-[#404040] px-2.5 py-1 text-xs text-[#d4d4d4]"
                            >
                              {source}
                            </span>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-muted-foreground">
                      {tenant.contact_email ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                      {formatLocaleDateTime(tenant.created_at)}
                    </td>
                    <td
                      className="px-6 py-4 text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Link
                        href={`/dashboard/admin/tenants/${tenant.tenant_id}`}
                        className="inline-flex items-center gap-1 text-sm font-bold text-primary transition-opacity hover:opacity-80"
                      >
                        Open
                        <ChevronRight className="size-4" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
