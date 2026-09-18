"use client";

import { History } from "lucide-react";

import { formatLocaleDateTime } from "@/lib/datetime";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
  TABLE_HEAD,
  TABLE_ROW,
  runStateTone,
  titleCase,
} from "@/lib/cluster-display";
import type { AnalysisRun } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AnalysisRunsCard({
  runs,
  total,
  canRetry,
  retrying,
  onRetry,
}: {
  runs: AnalysisRun[];
  total: number;
  canRetry: boolean;
  retrying: boolean;
  onRetry: () => void;
}) {
  const latest = runs[0];
  const truncated = total > runs.length;
  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className={PANEL_TITLE}>
            <History className="size-4 text-primary" />
            Analysis runs
            {total > 0 ? (
              <span className="text-sm font-normal text-muted-foreground">
                {total.toLocaleString("en-US")}
              </span>
            ) : null}
          </h3>
          <p className={PANEL_NOTE}>
            Durable execution and retry history. Dead letters remain available
            for audit.
            {truncated
              ? ` Showing the ${runs.length.toLocaleString("en-US")} most recent of ${total.toLocaleString("en-US")}.`
              : ""}
          </p>
        </div>
        {canRetry && latest?.state === "FAILED" ? (
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying}
            className="h-10 shrink-0 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {retrying ? "Scheduling…" : "Retry failed analysis"}
          </button>
        ) : null}
      </div>

      {runs.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">
          No analysis request has been recorded.
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-lg">
          <table className="w-full min-w-[640px] text-left">
            <thead className={TABLE_HEAD}>
              <tr>
                <th className="px-4 py-3">Version</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Attempts</th>
                <th className="px-4 py-3">Retry cycle</th>
                <th className="px-4 py-3">Updated</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.analysis_run_id} className={TABLE_ROW}>
                  <td className="px-4 py-3 text-sm text-foreground">
                    v{run.requested_analysis_version}
                  </td>
                  <td className="px-4 py-3">
                    <span className={cn(PILL, runStateTone(run.state))}>
                      {titleCase(run.state)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {run.attempts_total}
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {run.retry_cycle}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                    {formatLocaleDateTime(run.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
