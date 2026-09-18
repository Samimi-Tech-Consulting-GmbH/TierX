"use client";

import { useCallback, useEffect, useState } from "react";
import { AnalysisRunsCard } from "@/components/analysis-runs-card";
import { AnalysisSummaryCard } from "@/components/analysis-summary-card";
import { AlertClusterCard } from "@/components/alert-cluster-card";
import { listAlertAnalysisRuns } from "@/lib/api";
import type { AlertDocument, AnalysisRun } from "@/lib/types";

export function AlertAnalysisPanel({
  tenantId,
  alert,
  adminView = false,
}: {
  tenantId: string;
  alert: AlertDocument;
  adminView?: boolean;
}) {
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [runTotal, setRunTotal] = useState(0);

  const load = useCallback(async () => {
    if (alert.cluster_id) {
      setRuns([]);
      setRunTotal(0);
      return;
    }
    try {
      const page = await listAlertAnalysisRuns(tenantId, alert.alert_id);
      setRuns(page.items);
      setRunTotal(page.total);
    } catch {
      setRuns([]);
      setRunTotal(0);
    }
  }, [tenantId, alert.alert_id, alert.cluster_id]);

  useEffect(() => {
    void load();
  }, [load]);

  const clusterHref = alert.alert_analysis?.superseded_by_cluster_id
    ? adminView
      ? `/dashboard/admin/tenants/${tenantId}/clusters/${alert.alert_analysis.superseded_by_cluster_id}`
      : `/dashboard/${tenantId}/clusters/${alert.alert_analysis.superseded_by_cluster_id}`
    : undefined;

  return (
    <div className="space-y-8">
      <AlertClusterCard
        tenantId={tenantId}
        alert={alert}
        adminView={adminView}
      />
      {alert.alert_analysis ? (
        <AnalysisSummaryCard
          result={alert.alert_analysis}
          title="Legacy alert-scoped analysis"
          clusterHref={clusterHref}
        />
      ) : (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          {alert.cluster_id
            ? "Analysis is cluster-scoped. Open the cluster above to inspect its current result and run history."
            : alert.analysis_status
              ? `Legacy analysis status: ${alert.analysis_status}`
              : "No legacy alert-scoped analysis is available."}
        </div>
      )}
      {!alert.cluster_id ? (
        <AnalysisRunsCard
          runs={runs}
          total={runTotal}
          canRetry={false}
          retrying={false}
          onRetry={() => undefined}
        />
      ) : null}
    </div>
  );
}
