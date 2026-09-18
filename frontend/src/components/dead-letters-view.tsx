"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Inbox } from "lucide-react";

import type { DeadLetterRecord } from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  TABLE_HEAD,
  TABLE_ROW,
} from "@/lib/cluster-display";
import { scopedApi, scopedRoutes, type TenantScope } from "@/lib/tenant-scope";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const PAGE = 50;

export function DeadLettersView({
  tenantId,
  scope,
}: {
  tenantId: string;
  scope: TenantScope;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sinceHours = searchParams.get("since")
    ? Number(searchParams.get("since"))
    : undefined;

  const [items, setItems] = useState<DeadLetterRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSkip(0);
    scopedApi(scope)
      .listDeadLetters(tenantId, {
        skip: 0,
        limit: PAGE,
        since_hours: sinceHours,
      })
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setTotal(page.total);
        setSkip(page.items.length);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load dead-letter entries.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, sinceHours, scope]);

  async function loadMore() {
    if (skip >= total || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await scopedApi(scope).listDeadLetters(tenantId, {
        skip,
        limit: PAGE,
        since_hours: sinceHours,
      });
      setItems((prev) => [...prev, ...page.items]);
      setSkip((prev) => prev + page.items.length);
    } catch {
      setError("Could not load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  const routes = scopedRoutes(scope, tenantId);
  const base = routes.deadLetters;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start gap-4">
        <Button
          variant="ghost"
          size="icon"
          nativeButton={false}
          render={
            <Link href={scope === "admin" ? routes.home : routes.alerts} />
          }
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0 flex-1 space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">
            Dead letters{sinceHours ? ` (last ${sinceHours}h)` : ""}
          </h1>
          <p className="text-sm text-muted-foreground">
            Tenant <span className="font-mono text-foreground">{tenantId}</span>{" "}
            ·{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
              dead_letters
            </code>
          </p>
        </div>
      </div>

      <div className={PANEL}>
        <div className="flex flex-wrap items-center gap-3">
          <h3 className={PANEL_TITLE}>
            <Inbox className="size-4 text-primary" />
            Pipeline DLQ
          </h3>
          {!loading && (
            <span className="text-sm text-muted-foreground">
              {total.toLocaleString("en-US")} total
            </span>
          )}
        </div>
        <p className={PANEL_NOTE}>
          Select a row to open its full payload and metadata.
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
          ) : error && items.length === 0 ? (
            <p className="p-10 text-center text-sm text-destructive">{error}</p>
          ) : items.length === 0 ? (
            <p className="p-10 text-center text-sm text-muted-foreground">
              No dead-letter records.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg">
              <table className="w-full min-w-[860px] text-left">
                <thead className={TABLE_HEAD}>
                  <tr>
                    <th className="px-4 py-3">Alert ID</th>
                    <th className="px-4 py-3">Error</th>
                    <th className="px-4 py-3">Stage</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Dead-lettered</th>
                    <th className="px-4 py-3">Received</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => (
                    <tr
                      key={row.id}
                      onClick={() => router.push(`${base}/${row.id}`)}
                      className={cn(
                        "cursor-pointer transition-colors hover:bg-white/5",
                        TABLE_ROW,
                      )}
                    >
                      <td className="max-w-[200px] px-4 py-3">
                        <span className="block truncate font-mono text-xs text-muted-foreground">
                          {row.alert_id ?? "—"}
                        </span>
                      </td>
                      <td className="max-w-[200px] px-4 py-3">
                        <span className="block truncate text-sm font-medium text-[#f87171]">
                          {row.error_type ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="rounded-md bg-[#404040] px-2.5 py-1 text-xs text-[#d4d4d4]">
                          {row.failed_stage ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-muted-foreground">
                        {row.source_system ?? "—"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                        {formatLocaleDateTime(row.dead_lettered_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                        {formatLocaleDateTime(row.received_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {items.length > 0 && items.length < total && (
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="mt-4 h-10 rounded-md bg-[#404040] px-5 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a] disabled:opacity-40"
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        )}
        {error && items.length > 0 ? (
          <p className="mt-4 text-sm text-destructive">{error}</p>
        ) : null}
      </div>
    </div>
  );
}
