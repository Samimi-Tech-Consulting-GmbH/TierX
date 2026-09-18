"use client";

import { Bell, CircleCheck, Network, TriangleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { DashboardKpis, DashboardCoverage } from "@/lib/types";
import { cn } from "@/lib/utils";

interface KpiSpec {
  key: keyof DashboardKpis;
  label: string;
  icon: LucideIcon;
  accent: string;
}

const KPIS: KpiSpec[] = [
  {
    key: "critical_alerts",
    label: "Critical Alerts",
    icon: Bell,
    accent: "bg-[#dc2626]",
  },
  {
    key: "open_alerts",
    label: "Open Alerts",
    icon: TriangleAlert,
    accent: "bg-[#d97706]",
  },
  {
    key: "active_clusters",
    label: "Active Clusters",
    icon: Network,
    accent: "bg-primary",
  },
  {
    key: "resolved_incidents",
    label: "Resolved Incidents",
    icon: CircleCheck,
    accent: "bg-[#16a34a]",
  },
];

export function PlatformKpiRow({
  summary,
  loading,
  error,
}: {
  summary: { kpis: DashboardKpis; coverage?: DashboardCoverage } | null;
  loading: boolean;
  error: string | null;
}) {
  const kpis = summary?.kpis;

  return (
    <div className="space-y-3">
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        {KPIS.map(({ key, label, icon: Icon, accent }) => (
          <div
            key={key}
            className="flex items-center gap-4 rounded-lg bg-card px-6 py-5"
          >
            <span
              className={cn(
                "flex size-12 shrink-0 items-center justify-center rounded-lg",
                accent,
              )}
            >
              <Icon className="size-6 text-white" />
            </span>
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">{label}</p>
              <div className="mt-1 text-2xl font-bold">
                {loading ? (
                  <span className="inline-block h-7 w-14 animate-pulse rounded bg-white/10" />
                ) : error ? (
                  <span className="text-muted-foreground">–</span>
                ) : (
                  kpis?.[key].toLocaleString("en-US")
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {error && (
        <p className="text-xs text-destructive">
          Metrics could not be loaded: {error}
        </p>
      )}

      {!error && !loading && summary?.coverage?.partial && (
        <p role="alert" className="text-xs text-[#fbbf24]">
          Partial data: {summary.coverage.failed_tenants} of{" "}
          {summary.coverage.eligible_tenants} tenant(s) could not be read. The
          displayed totals are incomplete.
        </p>
      )}
    </div>
  );
}
