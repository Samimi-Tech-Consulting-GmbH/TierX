"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";

import { getPlatformAlertStats, listAllAlerts } from "@/lib/api";
import type { AlertStats, PlatformAlert } from "@/lib/types";
import { alertTypeLabel, severityOf, statusTone } from "@/lib/alert-display";
import { formatLocaleDateTime } from "@/lib/datetime";
import { PILL } from "@/lib/cluster-display";
import {
  PlatformListView,
  type PlatformColumn,
} from "@/components/platform-list-view";
import { cn } from "@/lib/utils";
import { AlertSeverityKpiRow } from "@/components/dashboard/alert-severity-kpi-row";

const COLUMNS: PlatformColumn<PlatformAlert>[] = [
  {
    key: "alert",
    header: "Alert",
    className: "max-w-[280px]",
    render: (row) => (
      <>
        <span className="block truncate text-sm font-bold text-foreground">
          {alertTypeLabel(row.alert_type)}
        </span>
        <span className="block truncate font-mono text-xs text-muted-foreground">
          {row.alert_id}
        </span>
      </>
    ),
  },
  {
    key: "severity",
    header: "Severity",
    render: (row) => (
      <span className="text-sm text-foreground">{severityOf(row).label}</span>
    ),
  },
  {
    key: "status",
    header: "Status",
    render: (row) => (
      <span className={cn(PILL, statusTone(row.status))}>
        {row.status ?? "—"}
      </span>
    ),
  },
  {
    key: "source",
    header: "Source",
    render: (row) => (
      <span className="text-sm text-muted-foreground">{row.source_system}</span>
    ),
  },
  {
    key: "created",
    header: "Created",
    render: (row) => (
      <span className="whitespace-nowrap text-sm text-muted-foreground">
        {formatLocaleDateTime(row.created_at)}
      </span>
    ),
  },
];

export default function AllTenantsAlertsPage() {
  const fetchPage = useCallback(
    (params: {
      q?: string;
      skip: number;
      limit: number;
      since_hours?: number;
    }) => listAllAlerts(params),
    [],
  );

  return (
    <PlatformListView<PlatformAlert>
      title="Alerts Management"
      description="Alerts from every tenant. Open one to work in the tenant that owns it."
      icon={Bell}
      searchPlaceholder="Search alert id, type or source…"
      columns={COLUMNS}
      fetchPage={fetchPage}
      rowKey={(row) => `${row.tenant_id}:${row.alert_id}`}
      hrefFor={(row) =>
        row.tenant_id
          ? `/dashboard/admin/tenants/${row.tenant_id}/alerts/${encodeURIComponent(row.alert_id)}`
          : null
      }
      emptyLabel="No alerts on the platform yet."
      showPeriodFilter
      renderTopContent={(filters) => <PlatformAlertKpis filters={filters} />}
    />
  );
}

function PlatformAlertKpis({
  filters,
}: {
  filters: { q?: string; since_hours?: number };
}) {
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { q, since_hours: sinceHours } = filters;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPlatformAlertStats({ q, since_hours: sinceHours })
      .then((value) => {
        if (!cancelled) setStats(value);
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
  }, [q, sinceHours]);

  return <AlertSeverityKpiRow stats={stats} loading={loading} error={error} />;
}
