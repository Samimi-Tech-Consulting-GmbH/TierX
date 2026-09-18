"use client";

import {
  CircleAlert,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { StatCard } from "@/components/dashboard/stat-card";
import type { AlertStats } from "@/lib/types";

export function AlertSeverityKpiRow({
  stats,
  loading,
  error,
}: {
  stats: AlertStats | null;
  loading: boolean;
  error: string | null;
}) {
  const cards = [
    {
      label: "Critical",
      value: stats?.severity.CRITICAL,
      icon: <ShieldAlert className="size-5 text-[#f87171]" />,
      iconClass: "bg-[#dc2626]/20",
    },
    {
      label: "High",
      value: stats?.severity.HIGH,
      icon: <TriangleAlert className="size-5 text-[#fbbf24]" />,
      iconClass: "bg-[#d97706]/20",
    },
    {
      label: "Medium",
      value: stats?.severity.MEDIUM,
      icon: <CircleAlert className="size-5 text-[#fde047]" />,
      iconClass: "bg-[#eab308]/20",
    },
    {
      label: "Low",
      value: stats?.severity.LOW,
      icon: <ShieldCheck className="size-5 text-[#60a5fa]" />,
      iconClass: "bg-[#2563eb]/20",
    },
  ];

  return (
    <div className="space-y-3">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <StatCard
            key={card.label}
            label={card.label}
            value={loading ? "…" : error ? "–" : String(card.value ?? 0)}
            hint={
              stats
                ? `of ${stats.filtered_total} filtered alerts`
                : "Current filter"
            }
            icon={card.icon}
            iconClass={card.iconClass}
          />
        ))}
      </div>
      {error ? (
        <p className="text-xs text-destructive">
          Metrics could not be loaded: {error}
        </p>
      ) : null}
      {!loading && !error && (stats?.severity.UNKNOWN ?? 0) > 0 ? (
        <p role="alert" className="text-xs text-[#fbbf24]">
          {stats?.severity.UNKNOWN.toLocaleString("en-US")} filtered alert(s) have
          unknown severity and are not included in the four cards.
        </p>
      ) : null}
    </div>
  );
}
