"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Search } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { PlatformPage, TenantOwned } from "@/lib/types";
import { TIME_RANGES, TIME_RANGE_ITEMS } from "@/lib/alert-display";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  TABLE_HEAD,
  TABLE_ROW,
} from "@/lib/cluster-display";
import {
  PAGE_SIZES,
  TablePaginationFooter,
} from "@/components/dashboard/pagination";
import { cn } from "@/lib/utils";

export interface PlatformColumn<T> {
  key: string;
  header: string;
  className?: string;
  render: (row: T) => React.ReactNode;
}

/**
 * The all-tenants view of a section. Every row belongs to a different tenant,
 * so the server does the searching and paging across tenants and returns each
 * row's owner; the client only renders and routes.
 */
export function PlatformListView<T extends TenantOwned>({
  title,
  description,
  icon: Icon,
  searchPlaceholder,
  columns,
  fetchPage,
  rowKey,
  hrefFor,
  emptyLabel,
  showPeriodFilter = false,
  renderTopContent,
}: {
  title: string;
  description: string;
  icon: LucideIcon;
  searchPlaceholder: string;
  columns: PlatformColumn<T>[];
  fetchPage: (params: {
    q?: string;
    skip: number;
    limit: number;
    since_hours?: number;
  }) => Promise<PlatformPage<T>>;
  rowKey: (row: T) => string;
  hrefFor: (row: T) => string | null;
  emptyLabel: string;
  showPeriodFilter?: boolean;
  renderTopContent?: (filters: {
    q?: string;
    since_hours?: number;
  }) => React.ReactNode;
}) {
  const router = useRouter();
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[1]);
  const [searchInput, setSearchInput] = useState("");
  const appliedQ = useDebouncedValue(searchInput.trim());
  const [draftSince, setDraftSince] = useState("all");
  const [appliedSince, setAppliedSince] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const hasPendingChanges = draftSince !== appliedSince;
  const sinceHours = TIME_RANGES.find((r) => r.value === appliedSince)?.hours;
  const searching = appliedQ.length > 0;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPage({
      q: appliedQ || undefined,
      skip: page * pageSize,
      limit: pageSize,
      since_hours: sinceHours,
    })
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
      })
      .catch(() => {
        if (!cancelled) {
          setItems([]);
          setError(
            "Could not load this list across tenants. The platform-wide endpoint may not be available yet.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [appliedQ, sinceHours, page, pageSize, fetchPage]);

  function applyFilters() {
    setAppliedSince(draftSince);
    setPage(0);
  }

  const periodLabel =
    showPeriodFilter && sinceHours != null
      ? TIME_RANGES.find((r) => r.value === appliedSince)?.label
      : null;
  const allColumns = useMemo<PlatformColumn<T>[]>(
    () => [
      ...columns,
      {
        key: "__tenant",
        header: "Tenant",
        className: "max-w-[200px]",
        render: (row) => (
          <span className="block truncate text-sm text-muted-foreground">
            {row.tenant_name ?? row.tenant_id ?? "—"}
          </span>
        ),
      },
    ],
    [columns],
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          All tenants · {total.toLocaleString("en-US")}{" "}
          {searching
            ? total === 1
              ? "match"
              : "matches"
            : total === 1
              ? "record"
              : "records"}
          {periodLabel ? ` · ${periodLabel}` : ""}
        </p>
      </div>

      {renderTopContent?.({
        q: appliedQ || undefined,
        since_hours: sinceHours,
      })}

      <div className="flex flex-wrap items-center gap-4 rounded-lg bg-card px-6 py-4">
        {showPeriodFilter ? (
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">Period:</span>
            <Select
              items={TIME_RANGE_ITEMS}
              value={draftSince}
              onValueChange={(v) => setDraftSince(v ?? "all")}
            >
              <SelectTrigger
                aria-label="Period"
                className="h-10 w-[190px] bg-[#404040]"
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
          </div>
        ) : null}

        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-10 bg-[#404040] pl-9"
            placeholder={searchPlaceholder}
            value={searchInput}
            onChange={(event) => {
              setSearchInput(event.target.value);
              setPage(0);
            }}
            autoComplete="off"
          />
        </div>
        {showPeriodFilter ? (
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
        ) : null}
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <Icon className="size-4 text-primary" />
          {title}
        </h3>
        <p className={PANEL_NOTE}>{description}</p>

        <div className="mt-4">
          {loading ? (
            <div className="flex h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-5 animate-spin" />
              Loading…
            </div>
          ) : error ? (
            <p className="p-10 text-center text-sm text-destructive">{error}</p>
          ) : items.length === 0 ? (
            <p className="p-10 text-center text-sm text-muted-foreground">
              {searching ? "No matches across any tenant." : emptyLabel}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg">
              <table className="w-full min-w-[900px] text-left">
                <thead className={TABLE_HEAD}>
                  <tr>
                    {allColumns.map((column) => (
                      <th key={column.key} className="px-4 py-3">
                        {column.header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => {
                    const href = hrefFor(row);
                    return (
                      <tr
                        key={rowKey(row)}
                        onClick={() => href && router.push(href)}
                        className={cn(
                          TABLE_ROW,
                          href
                            ? "cursor-pointer transition-colors hover:bg-white/5"
                            : undefined,
                        )}
                      >
                        {allColumns.map((column) => (
                          <td
                            key={column.key}
                            className={cn("px-4 py-3", column.className)}
                          >
                            {column.render(row)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {!loading && !error && items.length > 0 ? (
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
      ) : null}
    </div>
  );
}
