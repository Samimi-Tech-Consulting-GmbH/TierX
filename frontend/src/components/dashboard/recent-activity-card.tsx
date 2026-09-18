"use client";

import { timeAgo } from "@/lib/datetime";
import type { PlatformDashboardSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type ActivityKind = "alert" | "cluster";

const KIND_DOT: Record<ActivityKind, string> = {
  alert: "border-[#f87171]",
  cluster: "border-[#60a5fa]",
};

export function RecentActivityCard({
  className,
  summary,
  loading,
  error,
}: {
  className?: string;
  summary: PlatformDashboardSummary | null;
  loading: boolean;
  error: string | null;
}) {
  const entries = summary?.recent_activity.map((entry, index) => ({
    key: entry.alert_id ?? entry.cluster_id ?? `${entry.occurred_at}:${index}`,
    kind: (entry.kind === "CRITICAL_ALERT" ? "alert" : "cluster") as ActivityKind,
    title:
      entry.kind === "CRITICAL_ALERT"
        ? "Critical alert detected"
        : "New cluster identified",
    at: new Date(entry.occurred_at),
  }));

  return (
    <div className={cn("rounded-lg bg-card px-6 py-5", className)}>
      <h2 className="text-lg font-bold">Recent Activity</h2>

      <div className="mt-5 space-y-4">
        {loading ? (
          Array.from({ length: 2 }).map((_, index) => (
            <div key={index} className="flex items-start gap-3">
              <span className="mt-1 size-3 shrink-0 animate-pulse rounded-full bg-white/10" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <span className="block h-3.5 w-3/4 animate-pulse rounded bg-white/10" />
                <span className="block h-3 w-1/3 animate-pulse rounded bg-white/5" />
              </div>
            </div>
          ))
        ) : error ? (
          <p className="text-sm text-destructive">
            Activity could not be loaded: {error}
          </p>
        ) : entries && entries.length > 0 ? (
          entries.map((entry) => (
            <div key={entry.key} className="flex items-start gap-3">
              <span
                className={cn(
                  "mt-1 size-3 shrink-0 rounded-full border-2",
                  KIND_DOT[entry.kind],
                )}
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-bold">{entry.title}</p>
                <p className="text-xs text-muted-foreground">
                  {timeAgo(entry.at)}
                </p>
              </div>
            </div>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">No recent activity.</p>
        )}
      </div>
    </div>
  );
}
