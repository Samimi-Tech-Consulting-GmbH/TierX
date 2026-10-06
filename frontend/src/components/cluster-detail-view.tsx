"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Bell,
  ChessKing,
  FileClock,
  List,
  Network,
  Sparkles,
  Workflow,
} from "lucide-react";
import { toast } from "sonner";

import { AnalysisRunsCard } from "@/components/analysis-runs-card";
import { PeopleArrows } from "@/components/icons/people-arrows";
import {
  PAGE_SIZES,
  TablePaginationFooter,
} from "@/components/dashboard/pagination";
import { Input } from "@/components/ui/input";
import {
  addClusterNote,
  assignCluster,
  getCluster,
  getClusterAlerts,
  getClusterSummaryHistory,
  listClusterAnalysisRuns,
  retryClusterAnalysis,
  setClusterVerdict,
  updateClusterStatus,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatLocaleDateTime, formatShortDateTime } from "@/lib/datetime";
import {
  alertTypeLabel,
  severityFromValue,
  severityOf,
  statusTone,
} from "@/lib/alert-display";
import {
  confidenceTone,
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
  TABLE_HEAD,
  TABLE_ROW,
  titleCase,
} from "@/lib/cluster-display";
import {
  UserRole,
  type AlertDocument,
  type AnalysisResult,
  type AnalysisRun,
  type ClusterDocument,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTION =
  "h-10 rounded-md px-4 text-sm font-bold text-foreground transition-colors";

const VERDICTS = [
  { value: "TRUE_POSITIVE", tone: "bg-destructive text-white" },
  { value: "FALSE_POSITIVE", tone: "bg-[#525252] text-white" },
  { value: "BENIGN", tone: "bg-[#16a34a] text-white" },
] as const;

const TRANSITIONS: Record<string, string[]> = {
  OPEN: ["UNDER_INVESTIGATION"],
  UNDER_INVESTIGATION: ["ESCALATED", "CLOSED", "FALSE_POSITIVE"],
  ESCALATED: ["CLOSED", "FALSE_POSITIVE"],
  CLOSED: ["OPEN"],
  FALSE_POSITIVE: [],
};

const TECHNIQUE_TONES = [
  "text-[#f87171]",
  "text-[#fbbf24]",
  "text-[#c084fc]",
  "text-[#60a5fa]",
  "text-[#4ade80]",
];

const TACTIC_TONES = [
  "text-[#dc2626]",
  "text-[#d97706]",
  "text-[#eab308]",
  "text-[#2563eb]",
  "text-[#16a34a]",
];

const CONFIDENCE_FILL: Record<string, string> = {
  HIGH: "w-full",
  MEDIUM: "w-3/5",
  LOW: "w-1/4",
};

export function ClusterDetailView({
  tenantId,
  clusterId,
  alertBase,
}: {
  tenantId: string;
  clusterId: string;
  alertBase: string;
}) {
  const { user } = useAuth();
  const [cluster, setCluster] = useState<ClusterDocument | null>(null);
  const [alerts, setAlerts] = useState<AlertDocument[]>([]);
  const [alertTotal, setAlertTotal] = useState(0);
  const [alertPage, setAlertPage] = useState(0);
  const [alertPageSize, setAlertPageSize] = useState<number>(PAGE_SIZES[2]);
  const [alertsLoading, setAlertsLoading] = useState(true);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [history, setHistory] = useState<AnalysisResult[]>([]);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [runTotal, setRunTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [assignedTo, setAssignedTo] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const [clusterDoc, historyPage, runPage] = await Promise.all([
      getCluster(tenantId, clusterId),
      getClusterSummaryHistory(tenantId, clusterId),
      listClusterAnalysisRuns(tenantId, clusterId),
    ]);
    setCluster(clusterDoc);
    setHistory(historyPage.items);
    setRuns(runPage.items);
    setRunTotal(runPage.total);
    setAssignedTo(clusterDoc.assigned_to ?? "");
  }, [tenantId, clusterId]);

  useEffect(() => {
    setLoading(true);
    setAlertPage(0);
    load()
      .catch(() => toast.error("Failed to load cluster"))
      .finally(() => setLoading(false));
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    setAlertsLoading(true);
    setAlertsError(null);
    getClusterAlerts(tenantId, clusterId, {
      skip: alertPage * alertPageSize,
      limit: alertPageSize,
    })
      .then((page) => {
        if (cancelled) return;
        setAlerts(page.items);
        setAlertTotal(page.total);
      })
      .catch(() => {
        if (!cancelled) {
          setAlerts([]);
          setAlertTotal(0);
          setAlertsError("Failed to load member alerts.");
          toast.error("Failed to load member alerts");
        }
      })
      .finally(() => {
        if (!cancelled) setAlertsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, clusterId, alertPage, alertPageSize]);

  const canMutate =
    user?.role === UserRole.PLATFORM_ADMIN ||
    user?.role === UserRole.TENANT_ADMIN;

  async function mutate(
    action: () => Promise<ClusterDocument>,
    message: string,
  ) {
    try {
      const updated = await action();
      setCluster((current) => ({
        ...updated,
        affected_host_count:
          updated.affected_host_count ?? current?.affected_host_count ?? 0,
      }));
      toast.success(message);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Update failed");
    }
  }

  async function retry() {
    setRetrying(true);
    try {
      await retryClusterAnalysis(tenantId, clusterId);
      toast.success("Analysis retry scheduled");
      await load();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4 rounded-lg bg-card p-6">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-16 animate-pulse rounded bg-white/5" />
        ))}
      </div>
    );
  }
  if (!cluster) {
    return (
      <p className="rounded-lg bg-card p-10 text-center text-sm text-destructive">
        Cluster not found.
      </p>
    );
  }

  const severity = severityFromValue(cluster.severity.max);
  const summary = cluster.summary;

  const affectedHosts = cluster.affected_host_count ?? 0;

  const techniques = Array.isArray(
    (cluster.correlation_basis as Record<string, unknown>)?.mitre_techniques,
  )
    ? ((cluster.correlation_basis as Record<string, unknown>)
        .mitre_techniques as string[])
    : [];

  const correlation = (cluster.correlation_basis ?? {}) as Record<
    string,
    unknown
  >;
  const sharedEntities = Array.isArray(correlation.shared_entities)
    ? (correlation.shared_entities as string[])
    : [];

  return (
    <div className="space-y-6">
      <div className="rounded-lg bg-card p-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <h2 className="font-mono text-xl font-bold text-foreground">
            {cluster.cluster_id}
          </h2>
          <span className={cn("text-sm font-semibold", severity.className)}>
            {severity.label}
          </span>
          <span className="text-xs text-[#d4d4d4]">
            {titleCase(cluster.status)}
          </span>
        </div>

        {summary ? (
          <p className="mt-3 text-sm leading-relaxed text-[#d4d4d4]">
            <span className="font-semibold text-foreground">
              {summary.headline}
            </span>{" "}
            — {summary.narrative}
          </p>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">
            No analysis result yet. The request may be pending, failed, or
            predate LLM instrumentation.
          </p>
        )}

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-7">
          <Stat label="Alerts" value={String(cluster.alert_count)} />
          <Stat label="Affected Hosts" value={String(affectedHosts)} />
          <Stat
            label="First Seen"
            value={formatShortDateTime(cluster.first_seen)}
          />
          <Stat
            label="Last Activity"
            value={formatShortDateTime(cluster.last_seen)}
          />
          <Stat
            label="Analysis"
            value={titleCase(cluster.analysis_status ?? "NOT_REQUESTED")}
          />
          <Stat
            label="Versions"
            value={`${cluster.analyzed_version}/${cluster.requested_analysis_version}`}
          />
          <Stat
            label="Last Analyzed"
            value={formatShortDateTime(cluster.last_analyzed_at)}
          />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {techniques.length > 0 && (
          <div className="rounded-lg bg-card p-6">
            <h3 className="flex items-center gap-2 text-base font-bold text-foreground">
              <PeopleArrows className="size-4 text-primary" />
              MITRE ATT&CK Techniques
            </h3>
            <div className="mt-4 space-y-2">
              {techniques.map((technique, index) => (
                <div
                  key={technique}
                  className="rounded-md bg-[#404040] px-4 py-3"
                >
                  <span
                    className={cn(
                      "font-mono text-sm font-semibold",
                      TECHNIQUE_TONES[index % TECHNIQUE_TONES.length],
                    )}
                  >
                    {technique}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {summary ? (
          <div className="rounded-lg bg-card p-6">
            <h3 className="flex items-center gap-2 text-base font-bold text-foreground">
              <ChessKing className="size-4 fill-current text-primary" />
              Tactics Identified
            </h3>
            {summary.kill_chain.length ? (
              <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
                {summary.kill_chain.map((tactic, index) => (
                  <span
                    key={tactic}
                    className={cn(
                      "text-sm font-medium",
                      TACTIC_TONES[index % TACTIC_TONES.length],
                    )}
                  >
                    {tactic}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm text-muted-foreground">
                No supported stages identified.
              </p>
            )}

            <div className="mt-5 rounded-lg bg-[#404040] p-4">
              <div className="text-sm font-bold text-foreground">
                Attack Chain Confidence
              </div>
              <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-[#262626]">
                <div
                  className={cn(
                    "h-full rounded-full bg-primary",
                    CONFIDENCE_FILL[summary.confidence] ?? "w-1/4",
                  )}
                />
              </div>
              <p className="mt-2 text-xs text-[#a3a3a3]">
                {summary.confidence} confidence in attack chain correlation
              </p>
            </div>
          </div>
        ) : null}
      </div>

      {summary ? (
        <div className="rounded-lg bg-card p-6">
          <h3 className="flex items-center gap-2 text-base font-bold text-foreground">
            <List className="size-4 text-primary" />
            Recommended Actions
          </h3>
          {summary.recommended_actions.length ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {summary.recommended_actions.map((action, index) => (
                <div
                  key={`${index}-${action}`}
                  className="rounded-lg bg-[#404040] p-4 text-sm text-[#d4d4d4]"
                >
                  {action}
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted-foreground">
              No recommended actions were returned.
            </p>
          )}
        </div>
      ) : null}

      {summary ? (
        <div className={PANEL}>
          <div className="flex flex-wrap items-center gap-3">
            <h3 className={PANEL_TITLE}>
              <Sparkles className="size-4 text-primary" />
              Current cluster analysis
            </h3>
            <span className={cn(PILL, confidenceTone(summary.confidence))}>
              {summary.confidence} confidence
            </span>
            <span className={cn(PILL, "bg-[#404040]")}>v{summary.version}</span>
          </div>
          <p className={PANEL_NOTE}>
            {summary.model} · generated{" "}
            {formatLocaleDateTime(summary.generated_at)}
          </p>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Stat label="Prompt" value={titleCase(summary.prompt_source)} />
            <Stat label="Trigger" value={titleCase(summary.trigger_reason)} />
            <Stat
              label="Request"
              value={summary.is_final ? "Final" : "Interim"}
            />
          </div>
        </div>
      ) : null}

      <AnalysisRunsCard
        runs={runs}
        total={runTotal}
        canRetry={canMutate}
        retrying={retrying}
        onRetry={() => void retry()}
      />

      {history.length > 1 ? (
        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>
            <FileClock className="size-4 text-primary" />
            Summary history
          </h3>
          <p className={PANEL_NOTE}>
            Full re-analysis versions after cluster membership changes.
          </p>
          <div className="mt-4 space-y-2">
            {history.map((item) => (
              <div
                key={item.version}
                className="rounded-lg bg-[#404040] px-4 py-3"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <span className={cn(PILL, "bg-[#525252]")}>
                    v{item.version}
                  </span>
                  <span className="min-w-0 flex-1 text-sm font-medium text-foreground">
                    {item.headline}
                  </span>
                </div>
                <div className="mt-1 text-xs text-[#a3a3a3]">
                  {formatLocaleDateTime(item.generated_at)} · {item.confidence}{" "}
                  confidence
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <Bell className="size-4 text-primary" />
          Member alerts
        </h3>
        <p className={PANEL_NOTE}>
          Standalone results remain on promoted alerts for audit.
        </p>
        {alertsLoading ? (
          <p className="mt-4 text-sm text-muted-foreground">
            Loading member alerts…
          </p>
        ) : null}
        {alertsError ? (
          <p className="mt-4 text-sm text-destructive">{alertsError}</p>
        ) : null}
        <div className="mt-4 overflow-x-auto rounded-lg">
          <table className="w-full min-w-[720px] text-left">
            <thead className={TABLE_HEAD}>
              <tr>
                <th className="px-4 py-3">Alert</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Standalone result</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => {
                const memberSeverity = severityOf(alert);
                return (
                  <tr key={alert.alert_id} className={TABLE_ROW}>
                    <td className="max-w-[200px] px-4 py-3">
                      <Link
                        href={`${alertBase}/${alert.alert_id}`}
                        className="block truncate font-mono text-xs text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {alert.alert_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-sm text-foreground">
                      {alertTypeLabel(alert.alert_type)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "text-sm font-bold",
                          memberSeverity.className,
                        )}
                      >
                        {memberSeverity.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn(PILL, statusTone(alert.status))}>
                        {alert.status ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">
                      {alert.alert_analysis ? "Preserved" : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!alertsLoading && !alertsError ? (
          <div className="mt-4">
            <TablePaginationFooter
              page={alertPage}
              pageSize={alertPageSize}
              total={alertTotal}
              onPageChange={setAlertPage}
              onPageSizeChange={(size) => {
                setAlertPageSize(size);
                setAlertPage(0);
              }}
            />
          </div>
        ) : null}
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <Network className="size-4 text-primary" />
          Correlation evidence
        </h3>
        <p className={PANEL_NOTE}>
          Why these alerts were grouped into one cluster.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-xs text-[#a3a3a3]">Method</span>
          <span className={cn(PILL, "bg-[#404040]")}>
            {titleCase(String(correlation.method ?? "—"))}
          </span>
        </div>

        {sharedEntities.length > 0 && (
          <div className="mt-4">
            <span className="text-xs text-[#a3a3a3]">Shared entities</span>
            <div className="mt-2 flex flex-wrap gap-2">
              {sharedEntities.map((entity) => (
                <span
                  key={entity}
                  className="rounded-md bg-[#404040] px-3 py-1.5 font-mono text-xs text-[#d4d4d4]"
                >
                  {entity}
                </span>
              ))}
            </div>
          </div>
        )}

        <details className="mt-4 group" open>
          <summary className="text-xs text-muted-foreground transition-colors hover:text-foreground">
            Raw correlation basis
          </summary>
          <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded-lg bg-[#171717] p-4 text-xs text-[#d4d4d4]">
            {JSON.stringify(cluster.correlation_basis, null, 2)}
          </pre>
        </details>
      </div>

      {canMutate ? (
        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>
            <Workflow className="size-4 text-primary" />
            Analyst workflow
          </h3>
          <p className={PANEL_NOTE}>
            These actions do not run automated response playbooks.
          </p>

          <div className="mt-4 space-y-5">
            <div className="space-y-2">
              <p className="text-xs text-[#a3a3a3]">
                Current workflow status: {titleCase(cluster.status)}
              </p>
              <span className="text-xs text-[#a3a3a3]">Change workflow status</span>
              <div className="flex flex-wrap gap-2">
                {(TRANSITIONS[cluster.status] ?? []).length === 0 && (
                  <span className="text-sm text-muted-foreground">
                    No transitions available from {titleCase(cluster.status)}.
                  </span>
                )}
                {(TRANSITIONS[cluster.status] ?? []).map((status) => (
                  <button
                    key={status}
                    type="button"
                    onClick={() =>
                      void mutate(
                        () => updateClusterStatus(tenantId, clusterId, status),
                        `Cluster moved to ${status}`,
                      )
                    }
                    className={cn(ACTION, "bg-[#404040] hover:bg-[#4a4a4a]")}
                  >
                    {status === "OPEN" ? "Reopen investigation" : `Move to ${titleCase(status)}`}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <span className="text-xs text-[#a3a3a3]">Verdict</span>
              <div className="flex flex-wrap gap-2">
                {VERDICTS.map(({ value, tone }) => (
                  <button
                    key={value}
                    type="button"
                    disabled={
                      !["CLOSED", "FALSE_POSITIVE"].includes(cluster.status)
                    }
                    onClick={() =>
                      void mutate(
                        () => setClusterVerdict(tenantId, clusterId, value),
                        `Verdict set to ${value}`,
                      )
                    }
                    className={cn(ACTION, tone, "disabled:opacity-40")}
                  >
                    {titleCase(value)}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <span className="text-xs text-[#a3a3a3]">Assignee</span>
              <div className="flex flex-wrap gap-2">
                <Input
                  value={assignedTo}
                  onChange={(event) => setAssignedTo(event.target.value)}
                  placeholder="Analyst email or identifier"
                  className="h-10 min-w-[220px] flex-1 bg-[#404040]"
                />
                <button
                  type="button"
                  onClick={() =>
                    void mutate(
                      () =>
                        assignCluster(tenantId, clusterId, assignedTo || null),
                      "Assignment updated",
                    )
                  }
                  className={cn(ACTION, "bg-primary text-primary-foreground")}
                >
                  Assign
                </button>
              </div>
            </div>

            <div className="space-y-2">
              <span className="text-xs text-[#a3a3a3]">Note</span>
              <div className="flex flex-wrap gap-2">
                <Input
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Add analyst note"
                  className="h-10 min-w-[220px] flex-1 bg-[#404040]"
                />
                <button
                  type="button"
                  disabled={!note.trim()}
                  onClick={() => {
                    const value = note.trim();
                    void mutate(
                      () => addClusterNote(tenantId, clusterId, value),
                      "Note added",
                    );
                    setNote("");
                  }}
                  className={cn(
                    ACTION,
                    "bg-primary text-primary-foreground disabled:opacity-40",
                  )}
                >
                  Add note
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-[#404040] px-4 py-3">
      <div className="text-xs text-[#a3a3a3]">{label}</div>
      <div className="mt-1 truncate text-lg font-bold text-foreground">
        {value}
      </div>
    </div>
  );
}
