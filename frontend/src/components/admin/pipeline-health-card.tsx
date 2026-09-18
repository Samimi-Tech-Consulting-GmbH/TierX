"use client";

import type { PipelineHealthSummary } from "@/lib/types";
import Link from "next/link";
import { Activity } from "lucide-react";

import { PANEL, PANEL_NOTE, PANEL_TITLE } from "@/lib/cluster-display";
import { cn } from "@/lib/utils";

interface Props {
  summary: PipelineHealthSummary | null;
  loading?: boolean;
  error?: string | null;
  /** When set, metric tiles become clickable and link to tenant alert pages. */
  tenantId?: string | null;
}

export function PipelineHealthCard({
  summary,
  loading,
  error,
  tenantId,
}: Props) {
  const alertsBase = tenantId
    ? `/dashboard/admin/tenants/${tenantId}/alerts`
    : undefined;

  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className={PANEL_TITLE}>
            <Activity className="size-4 text-primary" />
            Pipeline health
          </h3>
          <p className={PANEL_NOTE}>Alert counts from the tenant database.</p>
        </div>
        {alertsBase && (
          <Link
            href={alertsBase}
            className="text-sm font-bold text-primary transition-opacity hover:opacity-80"
          >
            View alerts
          </Link>
        )}
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-muted-foreground">Loading metrics…</p>
      ) : error ? (
        <p className="mt-4 text-sm text-destructive">{error}</p>
      ) : summary ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Metric label="Total alerts" value={summary.total_alerts} />
          <Metric
            label="Last 24h"
            value={summary.alerts_last_24h + summary.dead_letters_last_24h}
            subtitle={alertsBase ? "View filtered alerts" : undefined}
            href={alertsBase ? `${alertsBase}?since=24` : undefined}
          />
          <Metric label="Escalated" value={summary.escalated_count} />
          <Metric
            label="Error"
            value={summary.error_count}
            tone="text-[#dc2626]"
          />
          <Metric
            label="Dead letters"
            value={summary.dead_letter_count}
            subtitle={tenantId ? "Open list" : undefined}
            href={
              tenantId
                ? `/dashboard/admin/tenants/${tenantId}/dead-letters`
                : undefined
            }
            tone={summary.dead_letter_count > 0 ? "text-[#d97706]" : undefined}
          />
        </div>
      ) : null}
    </div>
  );
}

function Metric({
  label,
  value,
  subtitle,
  href,
  tone,
}: {
  label: string;
  value: number;
  subtitle?: string;
  href?: string;
  tone?: string;
}) {
  const inner = (
    <>
      <div className="text-xs text-[#a3a3a3]">{label}</div>
      <div
        className={cn(
          "mt-1 text-lg font-bold text-foreground",
          value > 0 && tone,
        )}
      >
        {value.toLocaleString("en-US")}
      </div>
      {subtitle ? (
        <div className="mt-1 text-[11px] text-primary">{subtitle}</div>
      ) : null}
    </>
  );

  const className = cn(
    "block w-full rounded-lg bg-[#404040] px-4 py-3 text-left transition-colors",
    href && "hover:bg-[#4a4a4a]",
  );

  if (href) {
    return (
      <Link href={href} className={className}>
        {inner}
      </Link>
    );
  }

  return <div className={className}>{inner}</div>;
}
