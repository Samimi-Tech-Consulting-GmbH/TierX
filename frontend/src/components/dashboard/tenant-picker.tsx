"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, Search } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { listTenantPage } from "@/lib/api";
import type { TenantDocument } from "@/lib/types";
import { TenantStatus } from "@/lib/types";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/dashboard/pagination";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 10;

const STATUS_ITEMS = [
  { value: "ALL", label: "All statuses" },
  ...Object.values(TenantStatus).map((s) => ({ value: s, label: s })),
];

const STATUS_TONE: Record<string, string> = {
  ACTIVE: "bg-[#16a34a]",
  ONBOARDING: "bg-[#d97706]",
  SUSPENDED: "bg-destructive",
  DELETED: "bg-[#525252]",
};

export function TenantPicker({
  title,
  description,
  hrefFor,
  action,
}: {
  title: string;
  description: string;
  hrefFor: (tenant: TenantDocument) => string;
  action?: { label: string; icon: LucideIcon };
}) {
  const [tenants, setTenants] = useState<TenantDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const [draftSearch, setDraftSearch] = useState("");
  const [draftStatus, setDraftStatus] = useState<string>("ALL");

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const settledSearch = useDebouncedValue(draftSearch);
  useEffect(() => {
    setSearch(settledSearch);
    setPage(0);
  }, [settledSearch]);

  const hasPendingChanges = draftStatus !== statusFilter;

  function applyFilters() {
    setStatusFilter(draftStatus);
    setPage(0);
  }

  const fetchTenants = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTenantPage({
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
        status:
          statusFilter !== "ALL" ? (statusFilter as TenantStatus) : undefined,
      });
      setTenants(data.items);
      setTotal(data.total);
    } catch {
      setError("Failed to load tenants.");
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter]);

  useEffect(() => {
    void fetchTenants();
  }, [fetchTenants]);

  const pageCount = Math.max(Math.ceil(total / PAGE_SIZE), 1);
  const firstRow = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastRow = Math.min((page + 1) * PAGE_SIZE, total);

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="text-base text-muted-foreground">{description}</p>
      </div>

      {/* Filter bar */}
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
            placeholder="Search tenants…"
            value={draftSearch}
            onChange={(e) => setDraftSearch(e.target.value)}
            className="h-10 bg-[#404040] pl-9"
          />
        </div>

        <div className="flex items-center gap-4">
          {!loading && !error && (
            <span className="text-sm text-muted-foreground">
              {total} tenant{total === 1 ? "" : "s"}
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

      {/* Table */}
      <div className="overflow-hidden rounded-lg bg-card">
        {loading ? (
          <div className="space-y-3 p-6">
            {Array.from({ length: 4 }).map((_, index) => (
              <div
                key={index}
                className="h-10 w-full animate-pulse rounded bg-white/5"
              />
            ))}
          </div>
        ) : error ? (
          <div className="flex flex-col items-center gap-3 p-10">
            <p className="text-sm text-destructive">{error}</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void fetchTenants()}
            >
              Retry
            </Button>
          </div>
        ) : tenants.length === 0 ? (
          <p className="p-10 text-center text-sm text-muted-foreground">
            No tenants match your filters.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead className="bg-[#171717]">
                <tr className="text-xs font-bold text-muted-foreground">
                  <th className="px-6 py-4">Display name</th>
                  <th className="px-6 py-4">Slug</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4 text-right">
                    {action ? "Actions" : ""}
                  </th>
                </tr>
              </thead>
              <tbody>
                {tenants.map((t) => (
                  <tr key={t.tenant_id} className="border-t border-white/5">
                    <td className="px-6 py-4 text-sm font-medium text-foreground">
                      <Link
                        href={hrefFor(t)}
                        className="rounded-sm underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {t.display_name}
                      </Link>
                    </td>
                    <td className="px-6 py-4 font-mono text-sm text-muted-foreground">
                      {t.name}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={cn(
                          "inline-flex rounded-full px-3 py-1 text-xs font-bold text-white",
                          STATUS_TONE[t.status] ?? "bg-[#525252]",
                        )}
                      >
                        {t.status}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right">
                      {action ? (
                        <Link
                          href={hrefFor(t)}
                          className="inline-flex items-center gap-2 rounded-md bg-[#404040] px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-[#4a4a4a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <action.icon className="size-4" />
                          {action.label}
                        </Link>
                      ) : (
                        <Link
                          href={hrefFor(t)}
                          aria-label={`Open ${t.display_name}`}
                          className="inline-flex rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <ChevronRight className="size-4" />
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {!loading && !error && tenants.length > 0 && (
        <div className="flex flex-wrap items-center gap-4">
          <span className="text-sm text-muted-foreground">
            {firstRow}–{lastRow} of {total}
          </span>
          <Pagination
            page={page}
            pageCount={pageCount}
            onPageChange={setPage}
            className="ml-auto"
          />
        </div>
      )}
    </div>
  );
}
