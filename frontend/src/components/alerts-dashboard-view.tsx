"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import type { AlertStats } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { AlertListView } from "@/components/alert-list-view";
import { AlertSeverityKpiRow } from "@/components/dashboard/alert-severity-kpi-row";
import { scopedApi, scopedRoutes, type TenantScope } from "@/lib/tenant-scope";
import { TIME_RANGES } from "@/lib/alert-display";

export function AlertsDashboardView({
  tenantId,
  scope,
}: {
  tenantId: string;
  scope: TenantScope;
}) {
  const searchParams = useSearchParams();
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const since = searchParams.get("since") ?? "all";
  const sinceHours = TIME_RANGES.find((range) => range.value === since)?.hours;
  const q = searchParams.get("q")?.trim() || undefined;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    scopedApi(scope)
      .alertStats(tenantId, { since_hours: sinceHours, q })
      .then((result) => {
        if (!cancelled) setStats(result);
      })
      .catch(() => {
        if (!cancelled) {
          setStats(null);
          setError("Failed to load alert metrics.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, scope, sinceHours, q]);

  const routes = scopedRoutes(scope, tenantId);
  const base = routes.alerts;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start gap-4">
        <Button
          variant="ghost"
          size="icon"
          nativeButton={false}
          render={<Link href={routes.home} />}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0 flex-1 space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">
            Alerts Management
          </h1>
          <p className="text-base text-muted-foreground">
            Monitor and manage all security alerts for this tenant.
          </p>
        </div>

        <Link
          href={routes.clusters}
          className="h-10 shrink-0 rounded-md bg-primary px-5 text-sm font-bold leading-10 text-primary-foreground transition-opacity hover:opacity-90"
        >
          Cluster Analysis
        </Link>
      </div>

      <AlertSeverityKpiRow stats={stats} loading={loading} error={error} />

      <AlertListView tenantId={tenantId} detailBase={base} scope={scope} />
    </div>
  );
}
