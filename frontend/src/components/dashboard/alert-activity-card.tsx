"use client";

import { useState } from "react";

import type {
  DashboardActivityBucket,
  PlatformDashboardSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type ActivityGranularity = "daily" | "weekly" | "monthly";

interface ActivityBucket {
  alerts: number;
  deadLetters: number;
}

const CAPTIONS: Record<ActivityGranularity, string> = {
  daily: "Last 24 Hours",
  weekly: "Last 7 Days",
  monthly: "Last 30 Days",
};

const RANGES: { key: ActivityGranularity; label: string }[] = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
];

const SERIES = [
  { key: "alerts" as const, label: "Alerts", color: "#2563eb", width: 6 },
  { key: "deadLetters" as const, label: "Dead letters", color: "#d4a017", width: 3 },
];

const VIEW_W = 700;
const VIEW_H = 220;
const PAD = { top: 20, right: 20, bottom: 20, left: 20 };
const INSET = { left: 18, right: 14, top: 10, bottom: 14 };

function ActivityChart({ buckets }: { buckets: ActivityBucket[] }) {
  const max = Math.max(
    ...buckets.flatMap((b) => [b.alerts, b.deadLetters]),
    1,
  );
  const innerH = VIEW_H - PAD.top - PAD.bottom;
  const baseline = PAD.top + innerH;

  const plotLeft = PAD.left + INSET.left;
  const plotRight = VIEW_W - PAD.right - INSET.right;
  const plotTop = PAD.top + INSET.top;
  const plotBottom = baseline - INSET.bottom;
  const plotW = plotRight - plotLeft;
  const plotH = plotBottom - plotTop;

  const x = (index: number) =>
    buckets.length === 1
      ? plotLeft + plotW / 2
      : plotLeft + (plotW * index) / (buckets.length - 1);
  const y = (value: number) => plotBottom - (plotH * value) / max;

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="none"
      className="h-[220px] w-full"
      role="img"
      aria-label="Alert and dead-letter volume over time"
    >
      {/* Axes */}
      <line
        x1={PAD.left}
        y1={PAD.top}
        x2={PAD.left}
        y2={baseline}
        stroke="white"
        strokeWidth={5}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <line
        x1={PAD.left}
        y1={baseline}
        x2={VIEW_W - PAD.right}
        y2={baseline}
        stroke="white"
        strokeWidth={5}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />

      {SERIES.map(({ key, color, width }) => (
        <polyline
          key={key}
          points={buckets.map((b, i) => `${x(i)},${y(b[key])}`).join(" ")}
          fill="none"
          stroke={color}
          strokeWidth={width}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

export function AlertActivityCard({
  className,
  summary,
  loading,
  error,
}: {
  className?: string;
  summary: PlatformDashboardSummary | null;
  loading: boolean;
  error: string | null;
}) {
  const [granularity, setGranularity] = useState<ActivityGranularity>("weekly");
  const buckets = summary?.activity[granularity].map(
    (bucket: DashboardActivityBucket): ActivityBucket => ({
      alerts: bucket.alerts,
      deadLetters: bucket.dead_letters,
    }),
  );
  const caption = CAPTIONS[granularity];
  const hasData = buckets?.some((b) => b.alerts > 0 || b.deadLetters > 0);

  return (
    <div className={cn("rounded-lg bg-card px-6 py-5", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-bold">Alert Activity ({caption})</h2>
        <div className="flex gap-2">
          {RANGES.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setGranularity(option.key)}
              aria-pressed={option.key === granularity}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs transition-colors",
                option.key === granularity
                  ? "bg-primary font-bold text-primary-foreground"
                  : "bg-[#404040] text-[#d4d4d4] hover:bg-[#4a4a4a]",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 flex items-center gap-5">
        {SERIES.map(({ key, label, color }) => (
          <span key={key} className="flex items-center gap-2 text-xs text-[#a3a3a3]">
            <span
              className="h-1 w-5 rounded-full"
              style={{ backgroundColor: color }}
            />
            {label}
          </span>
        ))}
      </div>

      <div className="mt-3">
        {loading ? (
          <div className="h-[252px] w-full animate-pulse bg-[#999999]/10" />
        ) : error ? (
          <p className="py-16 text-center text-sm text-destructive">
            Activity could not be loaded: {error}
          </p>
        ) : buckets && hasData ? (
          <div className="bg-[#999999]/10 p-4">
            <ActivityChart buckets={buckets} />
          </div>
        ) : (
          <p className="py-16 text-center text-sm text-muted-foreground">
            No alerts in this period.
          </p>
        )}
      </div>
    </div>
  );
}
