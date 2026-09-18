"use client";

import { Check, Circle } from "lucide-react";

import {
  ONBOARDING_GUIDE_HINTS,
  parseOnboardingRows,
} from "@/lib/onboarding-meta";
import { PANEL, PANEL_NOTE, PANEL_TITLE } from "@/lib/cluster-display";
import { ListChecks } from "lucide-react";

interface Props {
  data: Record<string, unknown>;
  variant: "admin" | "tenant";
}

export function OnboardingChecklistCard({ data, variant }: Props) {
  const rows = parseOnboardingRows(data);

  const done = rows.filter((row) => row.done).length;

  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-center gap-3">
        <h3 className={PANEL_TITLE}>
          <ListChecks className="size-4 text-primary" />
          Onboarding checklist
        </h3>
        <span className="text-sm text-muted-foreground">
          {done}/{rows.length} complete
        </span>
      </div>
      <p className={PANEL_NOTE}>
        {variant === "tenant"
          ? "Getting started steps for your tenant environment."
          : "Provisioning milestones tracked in the tenant database."}
      </p>

      {/* Progress mirrors the count above, so the state reads at a glance. */}
      <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-[#404040]">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{
            width: `${rows.length ? (done / rows.length) * 100 : 0}%`,
          }}
        />
      </div>

      <div className="mt-4 space-y-2">
        {rows.map((row) => (
          <div
            key={row.key}
            className="flex gap-3 rounded-lg bg-[#404040] px-4 py-3"
          >
            <div className="mt-0.5 shrink-0">
              {row.done ? (
                <Check className="size-4 text-[#16a34a]" />
              ) : (
                <Circle className="size-4 text-[#737373]" />
              )}
            </div>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-sm font-medium text-foreground">{row.label}</p>
              {row.timestamp && row.done && (
                <p className="text-xs text-[#a3a3a3]">
                  Completed{" "}
                  {new Date(row.timestamp).toLocaleString(undefined, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </p>
              )}
              {variant === "tenant" && !row.done && (
                <p className="text-sm text-muted-foreground">
                  {ONBOARDING_GUIDE_HINTS[row.key] ?? ""}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
