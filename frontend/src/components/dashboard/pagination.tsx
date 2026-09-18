"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export const PAGE_SIZES = [10, 25, 50] as const;

export function pageWindow(
  current: number,
  count: number,
  windowSize = 3,
): (number | null)[] {
  if (count <= 4) {
    return Array.from({ length: count }, (_, index) => index);
  }

  const start = Math.min(
    Math.max(current - 1, 0),
    Math.max(count - windowSize, 0),
  );
  const run: number[] = [];
  for (
    let page = start;
    page < Math.min(start + windowSize, count);
    page += 1
  ) {
    run.push(page);
  }

  const result: (number | null)[] = [];
  const first = run[0];
  const last = run[run.length - 1];

  if (first > 0) {
    result.push(0);
    if (first > 1) result.push(null);
  }
  result.push(...run);
  if (last < count - 1) {
    if (last < count - 2) result.push(null);
    result.push(count - 1);
  }
  return result;
}

const BOX =
  "flex h-9 min-w-9 items-center justify-center rounded-md px-2 text-sm transition-colors disabled:opacity-40";

export function Pagination({
  page,
  pageCount,
  onPageChange,
  className,
}: {
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  if (pageCount <= 1) return null;

  return (
    <nav
      aria-label="Pagination"
      className={cn("flex items-center gap-2", className)}
    >
      <button
        type="button"
        onClick={() => onPageChange(Math.max(page - 1, 0))}
        disabled={page === 0}
        aria-label="Previous page"
        className={cn(BOX, "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]")}
      >
        <ChevronLeft className="size-4" />
      </button>

      {pageWindow(page, pageCount).map((entry, index) =>
        entry === null ? (
          <span
            key={`gap-${index}`}
            aria-hidden="true"
            className="px-1 text-sm text-muted-foreground"
          >
            …
          </span>
        ) : (
          <button
            key={entry}
            type="button"
            onClick={() => onPageChange(entry)}
            aria-current={entry === page ? "page" : undefined}
            className={cn(
              BOX,
              entry === page
                ? "bg-primary font-bold text-primary-foreground"
                : "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]",
            )}
          >
            {entry + 1}
          </button>
        ),
      )}

      <button
        type="button"
        onClick={() => onPageChange(Math.min(page + 1, pageCount - 1))}
        disabled={page >= pageCount - 1}
        aria-label="Next page"
        className={cn(BOX, "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]")}
      >
        <ChevronRight className="size-4" />
      </button>
    </nav>
  );
}

/**
 * The footer every server-paged table shares: page size, visible range, pages.
 *
 * `total` is the row count across all pages, not the length of the current one.
 */
export function TablePaginationFooter({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  if (total === 0) return null;

  const pageCount = Math.max(Math.ceil(total / pageSize), 1);
  const firstRow = page * pageSize + 1;
  const lastRow = Math.min((page + 1) * pageSize, total);

  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-3">
        <span className="text-sm text-muted-foreground">Rows per page:</span>
        <Select
          value={String(pageSize)}
          onValueChange={(v) => onPageSizeChange(Number(v ?? PAGE_SIZES[1]))}
        >
          <SelectTrigger className="h-9 w-[84px] bg-[#404040]">
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
      </div>

      <span className="ml-auto text-sm text-muted-foreground">
        {firstRow.toLocaleString("en-US")}–{lastRow.toLocaleString("en-US")} of{" "}
        {total.toLocaleString("en-US")}
      </span>

      <Pagination
        page={page}
        pageCount={pageCount}
        onPageChange={onPageChange}
      />
    </div>
  );
}
