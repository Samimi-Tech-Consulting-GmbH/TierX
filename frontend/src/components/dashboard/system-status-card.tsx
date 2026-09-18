"use client";

import { Brain, CircleAlert, CircleCheck, Database } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { usePlatformHealth } from "@/lib/use-platform-health";
import { cn } from "@/lib/utils";

const ROWS: { key: string; label: string; icon: LucideIcon }[] = [
  { key: "mongodb", label: "Database", icon: Database },
  { key: "ollama", label: "LLM Service", icon: Brain },
];

function StatusBadge({ state }: { state: string | undefined }) {
  const online = state === "green";
  const Icon = online ? CircleCheck : CircleAlert;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold text-white",
        online ? "bg-[#16a34a]" : "bg-destructive",
      )}
    >
      <Icon className="size-3" />
      {online ? "Online" : "Offline"}
    </span>
  );
}

export function SystemStatusCard({ className }: { className?: string }) {
  const { health, loading, failed } = usePlatformHealth();

  return (
    <div className={cn("rounded-lg bg-card px-6 py-5", className)}>
      <h2 className="text-lg font-bold">System Status</h2>

      <div className="mt-5 space-y-4">
        {ROWS.map(({ key, label, icon: Icon }) => (
          <div key={key} className="flex items-center gap-3">
            <Icon className="size-4 shrink-0 text-primary" />
            <span className="flex-1 truncate text-sm text-[#d4d4d4]">
              {label}
            </span>
            {loading ? (
              <span className="h-6 w-20 animate-pulse rounded-full bg-white/10" />
            ) : (
              <StatusBadge state={failed ? undefined : health?.components[key]} />
            )}
          </div>
        ))}
      </div>

      {failed && (
        <p className="mt-4 text-xs text-destructive">
          Health endpoint unreachable.
        </p>
      )}
    </div>
  );
}
