"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Network } from "lucide-react";

import { getCluster } from "@/lib/api";
import { formatLocaleDateTime } from "@/lib/datetime";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
  analysisStatusTone,
  clusterStatusTone,
  confidenceTone,
  titleCase,
} from "@/lib/cluster-display";
import type { AlertDocument, ClusterDocument } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AlertClusterCard({
  tenantId,
  alert,
  adminView = false,
}: {
  tenantId: string;
  alert: AlertDocument;
  adminView?: boolean;
}) {
  const clusterId =
    alert.cluster_id ?? alert.alert_analysis?.superseded_by_cluster_id;
  const [cluster, setCluster] = useState<ClusterDocument | null>(null);
  const [loading, setLoading] = useState(Boolean(clusterId));
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    if (!clusterId) return;
    let active = true;
    setCluster(null);
    setLoading(true);
    setLoadFailed(false);
    getCluster(tenantId, clusterId)
      .then((document) => {
        if (active) setCluster(document);
      })
      .catch(() => {
        if (active) setLoadFailed(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tenantId, clusterId]);

  if (!clusterId) return null;

  const clusterHref = adminView
    ? `/dashboard/admin/tenants/${tenantId}/clusters/${clusterId}`
    : `/dashboard/${tenantId}/clusters/${clusterId}`;

  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-center gap-3">
        <h3 className={PANEL_TITLE}>
          <Network className="size-4 text-primary" />
          Clustered in
        </h3>
        {cluster ? (
          <span className={cn(PILL, clusterStatusTone(cluster.status))}>
            Workflow: {titleCase(cluster.status)}
          </span>
        ) : null}
        {cluster?.analysis_status ? (
          <span
            className={cn(
              "text-xs",
              analysisStatusTone(cluster.analysis_status),
            )}
          >
            {titleCase(cluster.analysis_status)}
          </span>
        ) : null}
      </div>
      <p className={PANEL_NOTE}>
        Every processed alert belongs to a cluster. This cluster contains the
        current single-alert or shared analysis.
      </p>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[#404040] p-4">
        <div className="min-w-0">
          <div className="text-xs text-[#a3a3a3]">Cluster ID</div>
          <Link
            className="break-all font-mono text-sm font-medium text-foreground transition-colors hover:text-primary"
            href={clusterHref}
          >
            {clusterId}
          </Link>
        </div>
        <Link
          href={clusterHref}
          className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90"
        >
          Open cluster analysis
          <ArrowRight className="size-4" />
        </Link>
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-muted-foreground">
          Loading cluster analysis…
        </p>
      ) : null}

      {loadFailed ? (
        <p className="mt-4 text-sm text-destructive">
          Cluster details could not be loaded. The direct link remains
          available.
        </p>
      ) : null}

      {cluster ? (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Members" value={String(cluster.alert_count)} />
            <Stat
              label="Accepting related alerts"
              value={cluster.is_open_for_grouping ? "Yes" : "No"}
            />
            <Stat
              label="Analysis"
              value={titleCase(cluster.analysis_status ?? "NOT_REQUESTED")}
            />
            <Stat
              label="Analysis version"
              value={`${cluster.analyzed_version}/${cluster.requested_analysis_version}`}
            />
          </div>

          {cluster.summary ? (
            <div className="mt-4 rounded-lg bg-[#404040] p-4">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-bold text-foreground">
                  Current cluster analysis includes this alert
                </span>
                <span
                  className={cn(
                    PILL,
                    confidenceTone(cluster.summary.confidence),
                  )}
                >
                  {cluster.summary.confidence} confidence
                </span>
                <span className={cn(PILL, "bg-[#525252]")}>
                  v{cluster.summary.version}
                </span>
              </div>
              <p className="mt-2 text-sm text-[#d4d4d4]">
                {cluster.summary.headline}
              </p>
              <p className="mt-1 text-xs text-[#a3a3a3]">
                Generated {formatLocaleDateTime(cluster.summary.generated_at)}
                {cluster.last_analyzed_at
                  ? ` · cluster updated ${formatLocaleDateTime(cluster.last_analyzed_at)}`
                  : ""}
              </p>
            </div>
          ) : (
            <p className="mt-4 rounded-lg bg-[#404040] p-4 text-sm text-muted-foreground">
              No completed cluster analysis is available yet. Open the cluster
              to inspect its current run state.
            </p>
          )}
        </>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-[#404040] px-4 py-3">
      <div className="text-xs text-[#a3a3a3]">{label}</div>
      <div className="mt-1 truncate text-sm font-bold text-foreground">
        {value}
      </div>
    </div>
  );
}
