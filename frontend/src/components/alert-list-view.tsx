"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, Search } from "lucide-react";

import { scopedApi, type TenantScope } from "@/lib/tenant-scope";
import { formatLocaleDateTime } from "@/lib/datetime";
import type { AlertDocument } from "@/lib/types";
import {
  TIME_RANGES,
  TIME_RANGE_ITEMS,
  alertTypeLabel,
  severityOf,
  statusTone,
} from "@/lib/alert-display";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  PAGE_SIZES,
  TablePaginationFooter,
} from "@/components/dashboard/pagination";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

export function AlertListView({
  tenantId,
  detailBase,
  scope = "admin",
}: {
  tenantId: string;
  detailBase: string;
  scope?: TenantScope;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const sinceParam = searchParams.get("since") ?? "all";
  const since = sinceParam;
  const queryParam = searchParams.get("q") ?? "";

  const [draftSince, setDraftSince] = useState(sinceParam);
  const [draftQuery, setDraftQuery] = useState(queryParam);

  const [items, setItems] = useState<AlertDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[1]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const hasPendingChanges = draftSince !== since;
  const sinceHours = TIME_RANGES.find((r) => r.value === since)?.hours;

  useEffect(() => {
    setDraftSince(sinceParam);
    setDraftQuery(queryParam);
    setPage(0);
  }, [sinceParam, queryParam]);

  function applyFilters() {
    const params = new URLSearchParams(searchParams.toString());
    if (draftSince === "all") params.delete("since");
    else params.set("since", draftSince);
    const query = params.toString();
    router.replace(query ? `?${query}` : "?", { scroll: false });
    setPage(0);
  }

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
    let cancelled = false;
    setLoading(true);
    setError(null);
    scopedApi(scope)
      .listAlerts(tenantId, {
        skip: page * pageSize,
        limit: pageSize,
        since_hours: sinceHours,
        q: queryParam || undefined,
      })
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load alerts.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, sinceHours, queryParam, page, pageSize, scope]);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center gap-4 rounded-lg bg-card px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">Period:</span>
          <Select
            items={TIME_RANGE_ITEMS}
            value={draftSince}
            onValueChange={(v) => setDraftSince(v ?? "all")}
          >
            <SelectTrigger className="h-10 w-[190px] bg-[#404040]">
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
        </div>

        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-10 bg-[#404040] pl-9"
            placeholder="Search alert id, type or source…"
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            autoComplete="off"
          />
        </div>

        <div className="flex items-center gap-4">
          {!loading && !error && (
            <span className="text-sm text-muted-foreground">
              {total.toLocaleString("en-US")}{" "}
              {queryParam
                ? total === 1
                  ? "match"
                  : "matches"
                : total === 1
                  ? "alert"
                  : "alerts"}
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
            {Array.from({ length: 6 }).map((_, index) => (
              <div
                key={index}
                className="h-10 w-full animate-pulse rounded bg-white/5"
              />
            ))}
          </div>
        ) : error && items.length === 0 ? (
          <p className="p-10 text-center text-sm text-destructive">{error}</p>
        ) : items.length === 0 ? (
          <p className="p-10 text-center text-sm text-muted-foreground">
            No alerts found.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left">
              <thead className="bg-[#171717]">
                <tr className="text-xs font-bold text-muted-foreground">
                  <th className="px-6 py-4">ID</th>
                  <th className="px-6 py-4">Alert name</th>
                  <th className="px-6 py-4">Severity</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Source</th>
                  <th className="px-6 py-4">Timestamp</th>
                  <th className="w-20 px-6 py-4">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => {
                  const severity = severityOf(row);
                  const href = `${detailBase}/${row.alert_id}`;
                  return (
                    <tr key={row.id} className="border-t border-white/5">
                      <td className="max-w-[180px] px-6 py-4">
                        <Link
                          href={href}
                          className="block truncate font-mono text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {row.alert_id}
                        </Link>
                      </td>
                      <td className="max-w-[220px] px-6 py-4">
                        <Link
                          href={href}
                          className="block truncate text-sm font-medium text-foreground underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {alertTypeLabel(row.alert_type)}
                        </Link>
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={cn(
                            "text-sm font-bold",
                            severity.className,
                          )}
                        >
                          {severity.label}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={cn(
                            "inline-flex rounded-full px-3 py-1 text-xs font-bold text-white",
                            statusTone(row.status),
                          )}
                        >
                          {row.status ?? "—"}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm text-muted-foreground">
                        {row.source_system}
                      </td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">
                        {formatLocaleDateTime(row.created_at)}
                      </td>
                      <td className="px-6 py-4">
                        <Link
                          href={href}
                          aria-label="View alert"
                          className="inline-flex rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <Eye className="size-4" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {!loading && !error && (
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

      {error && items.length > 0 && (
        <p className="text-sm text-destructive">{error}</p>
      )}
    </div>
  );
}
