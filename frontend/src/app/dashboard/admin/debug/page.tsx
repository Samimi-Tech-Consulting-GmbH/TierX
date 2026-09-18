"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  ChevronRight,
  Filter,
  LoaderCircle,
  RefreshCw,
  ScanSearch,
  Search,
  XCircle,
} from "lucide-react";

import { listDebugTraces } from "@/lib/api";
import type { ProcessingTraceSummary } from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import { formatDurationMs } from "@/lib/duration";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
  TABLE_HEAD,
  TABLE_ROW,
  runStateTone,
} from "@/lib/cluster-display";
import { Input } from "@/components/ui/input";
import { StatCard } from "@/components/dashboard/stat-card";
import {
  PAGE_SIZES,
  TablePaginationFooter,
} from "@/components/dashboard/pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

const STAGES = [
  "INGESTION",
  "VALIDATION",
  "NORMALIZATION",
  "FINGERPRINT",
  "ENRICHMENT",
  "ENRICHMENT_ACTION",
  "CORRELATION",
  "ANALYSIS",
  "DEAD_LETTER",
] as const;

const STAGE_ITEMS = [
  { value: "", label: "All stages" },
  ...STAGES.map((s) => ({ value: s, label: s.replaceAll("_", " ") })),
];

const OUTCOME_ITEMS = [
  { value: "", label: "All outcomes" },
  { value: "RUNNING", label: "Running" },
  { value: "SUCCEEDED", label: "Succeeded" },
  { value: "FAILED", label: "Failed" },
];

const WINDOW_ITEMS = [
  { value: "1", label: "Last hour" },
  { value: "24", label: "Last 24 hours" },
  { value: "168", label: "Last 7 days" },
  { value: "720", label: "Last 30 days" },
];

const DEFAULT_WINDOW = "168";

type Filters = {
  tenantId: string;
  stage: string;
  outcome: string;
  releaseVersion: string;
  releaseSha: string;
  sinceHours: string;
};

const EMPTY_FILTERS: Filters = {
  tenantId: "",
  stage: "",
  outcome: "",
  releaseVersion: "",
  releaseSha: "",
  sinceHours: DEFAULT_WINDOW,
};

function traceStateTone(state: string): string {
  return state === "STALLED" ? "bg-destructive" : runStateTone(state);
}

function releaseLabel(item: ProcessingTraceSummary): string {
  if (item.mixed_releases) return "Mixed versions";
  const version = item.release_version
    ? `v${item.release_version}`
    : "Version unavailable";
  const sha = item.release_sha ? item.release_sha.slice(0, 7) : "no SHA";
  return `${version} · ${sha}`;
}

export default function DebugTraceListPage() {
  const router = useRouter();
  const [items, setItems] = useState<ProcessingTraceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[1]);
  const [alertId, setAlertId] = useState("");
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filterRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const filtersActive =
    applied.tenantId !== "" ||
    applied.stage !== "" ||
    applied.outcome !== "" ||
    applied.releaseVersion !== "" ||
    applied.releaseSha !== "" ||
    applied.sinceHours !== DEFAULT_WINDOW;

  const hasPendingChanges = (
    Object.keys(EMPTY_FILTERS) as (keyof Filters)[]
  ).some((key) => draft[key] !== applied[key]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listDebugTraces({
        alert_id: alertId || undefined,
        tenant_id: applied.tenantId || undefined,
        stage: applied.stage || undefined,
        outcome: applied.outcome || undefined,
        release_version: applied.releaseVersion || undefined,
        release_sha: applied.releaseSha || undefined,
        since_hours: Number(applied.sinceHours),
        skip: page * pageSize,
        limit: pageSize,
      });
      setItems(result.items);
      setTotal(result.total);
    } catch {
      setError("Failed to load processing traces.");
    } finally {
      setLoading(false);
    }
  }, [alertId, applied, page, pageSize]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 250);
    return () => clearTimeout(timer);
  }, [load]);

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
    setApplied(draft);
    setPage(0);
    setFiltersOpen(false);
  }

  function resetFilters() {
    setDraft(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setPage(0);
    setFiltersOpen(false);
  }

  const pageStats = useMemo(() => {
    const succeeded = items.filter(
      (i) => i.terminal_state === "SUCCEEDED",
    ).length;
    const failed = items.filter((i) =>
      ["FAILED", "STALLED"].includes(i.terminal_state),
    ).length;
    const running = items.filter((i) => i.terminal_state === "RUNNING").length;
    return { succeeded, failed, running };
  }, [items]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Processing Debug
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            How alerts move through ingestion, validation, normalization,
            deduplication, enrichment, correlation, analysis, and dead-letter
            storage. Trace data is retained for seven days.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md bg-[#404040] px-5 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a] disabled:opacity-40"
        >
          <RefreshCw className={cn("size-4", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard
          label="Traces in window"
          value={total.toLocaleString("en-US")}
          hint={
            WINDOW_ITEMS.find(
              (w) => w.value === applied.sinceHours,
            )?.label.toLowerCase() ?? "selected window"
          }
          icon={<ScanSearch className="size-5 text-[#60a5fa]" />}
          iconClass="bg-[#2563eb]/20"
        />
        <StatCard
          label="Succeeded"
          value={`${pageStats.succeeded}`}
          hint="on this page"
          icon={<CheckCircle2 className="size-5 text-[#4ade80]" />}
          iconClass="bg-[#16a34a]/20"
        />
        <StatCard
          label="Failed or stalled"
          value={`${pageStats.failed}`}
          hint="on this page"
          icon={<XCircle className="size-5 text-[#f87171]" />}
          iconClass="bg-destructive/20"
        />
        <StatCard
          label="Running"
          value={`${pageStats.running}`}
          hint="on this page"
          icon={<LoaderCircle className="size-5 text-[#fbbf24]" />}
          iconClass="bg-[#d97706]/20"
        />
      </div>

      <div className="flex flex-wrap items-center gap-4 rounded-lg bg-card px-6 py-4">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-10 bg-[#404040] pl-9"
            placeholder="Exact alert ID"
            value={alertId}
            onChange={(event) => {
              setAlertId(event.target.value);
              setPage(0);
            }}
            autoComplete="off"
          />
        </div>

        <span className="text-sm text-muted-foreground">
          {total.toLocaleString("en-US")} trace{total === 1 ? "" : "s"}
        </span>

        <div className="relative" ref={filterRef}>
          <button
            type="button"
            onClick={() => setFiltersOpen((open) => !open)}
            aria-expanded={filtersOpen}
            aria-label="Filter traces"
            className={cn(
              "flex size-10 items-center justify-center rounded-md transition-colors",
              filtersActive
                ? "bg-primary text-primary-foreground"
                : "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]",
            )}
          >
            <Filter className="size-4" fill="currentColor" />
          </button>

          {filtersOpen && (
            <div className="absolute right-0 top-12 z-20 w-[280px] space-y-4 rounded-lg border border-[#404040] bg-card p-4 shadow-lg">
              <DraftSelect
                label="Stage"
                items={STAGE_ITEMS}
                value={draft.stage}
                onChange={(v) => setDraft((d) => ({ ...d, stage: v }))}
              />
              <DraftSelect
                label="Outcome"
                items={OUTCOME_ITEMS}
                value={draft.outcome}
                onChange={(v) => setDraft((d) => ({ ...d, outcome: v }))}
              />
              <DraftSelect
                label="Time window"
                items={WINDOW_ITEMS}
                value={draft.sinceHours}
                onChange={(v) =>
                  setDraft((d) => ({ ...d, sinceHours: v || DEFAULT_WINDOW }))
                }
              />
              <label className="block space-y-2">
                <span className="text-xs text-muted-foreground">Tenant ID</span>
                <Input
                  className="h-9 bg-[#404040]"
                  placeholder="Any tenant"
                  value={draft.tenantId}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, tenantId: e.target.value }))
                  }
                />
              </label>
              <label className="block space-y-2">
                <span className="text-xs text-muted-foreground">
                  Release version
                </span>
                <Input
                  className="h-9 bg-[#404040]"
                  placeholder="Any version"
                  value={draft.releaseVersion}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, releaseVersion: e.target.value }))
                  }
                />
              </label>
              <label className="block space-y-2">
                <span className="text-xs text-muted-foreground">
                  Release SHA
                </span>
                <Input
                  className="h-9 bg-[#404040]"
                  placeholder="Any SHA"
                  value={draft.releaseSha}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, releaseSha: e.target.value }))
                  }
                />
              </label>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={resetFilters}
                  className="h-9 flex-1 rounded-md bg-[#404040] text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={applyFilters}
                  className={cn(
                    "h-9 flex-1 rounded-md bg-primary text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90",
                    !hasPendingChanges && "opacity-60",
                  )}
                >
                  Apply
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <ScanSearch className="size-4 text-primary" />
          Recent alerts
        </h3>
        <p className={PANEL_NOTE}>
          Processing time sums completed stage durations and excludes idle gaps
          between later trace events. Select a row to inspect its timeline.
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
          ) : error ? (
            <p className="p-10 text-center text-sm text-destructive">{error}</p>
          ) : items.length === 0 ? (
            <p className="p-10 text-center text-sm text-muted-foreground">
              No traces match these filters. Alerts created before
              instrumentation have no trace data.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg">
              <table className="w-full min-w-[1000px] text-left">
                <thead className={TABLE_HEAD}>
                  <tr>
                    <th className="px-4 py-3">Alert</th>
                    <th className="px-4 py-3">Tenant</th>
                    <th className="px-4 py-3">Ingested</th>
                    <th className="px-4 py-3">Current stage</th>
                    <th className="px-4 py-3">Result</th>
                    <th className="px-4 py-3">Release</th>
                    <th className="px-4 py-3 text-right">Processing time</th>
                    <th className="px-4 py-3">Last event</th>
                    <th className="w-10 px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      key={item.alert_id}
                      onClick={() =>
                        router.push(
                          `/dashboard/admin/debug/alerts/${encodeURIComponent(item.alert_id)}`,
                        )
                      }
                      className={cn(
                        "cursor-pointer transition-colors hover:bg-white/5",
                        TABLE_ROW,
                      )}
                    >
                      <td className="max-w-[280px] px-4 py-3">
                        <span className="block truncate text-sm font-bold text-foreground">
                          {item.alert_type ?? "Unknown type"}
                        </span>
                        <span className="block truncate font-mono text-xs text-muted-foreground">
                          {item.alert_id}
                        </span>
                      </td>
                      <td className="max-w-[200px] px-4 py-3">
                        <span className="block truncate font-mono text-xs text-[#d4d4d4]">
                          {item.tenant_id ?? "—"}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                        {formatLocaleDateTime(item.first_seen_at)}
                      </td>
                      <td className="px-4 py-3 text-sm text-foreground">
                        {item.current_stage?.replaceAll("_", " ") ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            PILL,
                            traceStateTone(item.terminal_state),
                          )}
                        >
                          {item.terminal_state}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted-foreground">
                        {releaseLabel(item)}
                      </td>
                      <td className="px-4 py-3 text-right text-sm tabular-nums text-muted-foreground">
                        {item.processing_duration_ms != null
                          ? formatDurationMs(item.processing_duration_ms)
                          : "—"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                        {formatLocaleDateTime(item.last_seen_at)}
                      </td>
                      <td className="px-4 py-3">
                        <ChevronRight className="size-4 text-muted-foreground" />
                      </td>
                    </tr>
                  ))}
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

function DraftSelect({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block space-y-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Select
        items={items}
        value={value}
        onValueChange={(v) => onChange(v ?? "")}
      >
        <SelectTrigger className="h-9 w-full bg-[#404040]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}
