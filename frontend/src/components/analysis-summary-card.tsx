"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";

import { formatLocaleDateTime } from "@/lib/datetime";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
  confidenceTone,
  titleCase,
} from "@/lib/cluster-display";
import type { AnalysisResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export function AnalysisSummaryCard({
  result,
  title = "LLM analysis",
  clusterHref,
}: {
  result: AnalysisResult;
  title?: string;
  clusterHref?: string;
}) {
  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-center gap-3">
        <h3 className={PANEL_TITLE}>
          <Sparkles className="size-4 text-primary" />
          {title}
        </h3>
        <span className={cn(PILL, confidenceTone(result.confidence))}>
          {result.confidence} confidence
        </span>
        <span className={cn(PILL, "bg-[#525252]")}>v{result.version}</span>
      </div>
      <p className={PANEL_NOTE}>
        {result.model} · generated {formatLocaleDateTime(result.generated_at)}
      </p>

      {result.superseded_by_cluster_id ? (
        <div className="mt-4 rounded-lg border border-[#d97706]/40 bg-[#d97706]/10 p-4 text-sm text-[#fbbf24]">
          This standalone result was superseded by cluster{" "}
          {clusterHref ? (
            <Link className="font-mono underline" href={clusterHref}>
              {result.superseded_by_cluster_id}
            </Link>
          ) : (
            <span className="font-mono">{result.superseded_by_cluster_id}</span>
          )}
          .
        </div>
      ) : null}

      <div className="mt-4">
        <h4 className="text-sm font-bold text-foreground">{result.headline}</h4>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-[#d4d4d4]">
          {result.narrative}
        </p>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <div className="rounded-lg bg-[#404040] p-4">
          <h4 className="text-sm font-bold text-foreground">Kill chain</h4>
          {result.kill_chain.length ? (
            <ul className="mt-3 space-y-1.5 text-sm text-[#d4d4d4]">
              {result.kill_chain.map((item) => (
                <li key={item} className="flex gap-2">
                  <span aria-hidden="true" className="text-primary">
                    ·
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              No supported stages identified.
            </p>
          )}
        </div>

        <div className="rounded-lg bg-[#404040] p-4">
          <h4 className="text-sm font-bold text-foreground">
            Recommended actions
          </h4>
          {result.recommended_actions.length ? (
            <ol className="mt-3 space-y-1.5 text-sm text-[#d4d4d4]">
              {result.recommended_actions.map((item, index) => (
                <li key={`${index}-${item}`} className="flex gap-2">
                  <span className="font-bold text-primary">{index + 1}.</span>
                  {item}
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              No recommended actions were returned.
            </p>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span>Prompt: {titleCase(result.prompt_source)}</span>
        <span>Trigger: {titleCase(result.trigger_reason)}</span>
        <span>{result.is_final ? "Final request" : "Interim request"}</span>
      </div>
    </div>
  );
}
