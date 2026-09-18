"use client";

import { CircleAlert, CircleCheck, Menu } from "lucide-react";

import { useAuth } from "@/lib/auth";
import { usePlatformHealth } from "@/lib/use-platform-health";
import { cn } from "@/lib/utils";
import { TierXLogo } from "@/components/tierx-logo";

function HealthBadge() {
  const { health, loading, failed } = usePlatformHealth();

  if (loading) {
    return <span className="h-7 w-24 animate-pulse rounded-full bg-white/10" />;
  }

  const healthy = !failed && health?.status === "HEALTHY";
  const label = failed ? "UNKNOWN" : (health?.status ?? "UNKNOWN");
  const Icon = healthy ? CircleCheck : CircleAlert;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-bold text-white",
        healthy ? "bg-[#16a34a]" : "bg-destructive",
      )}
    >
      <Icon className="size-3.5" />
      {label}
    </span>
  );
}

export function DashboardHeader({ onMenuClick }: { onMenuClick: () => void }) {
  const { user } = useAuth();

  return (
    <header className="flex h-[76px] shrink-0 items-center gap-3 border-b border-[#404040] px-4 lg:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        aria-label="Open navigation"
        className="rounded-md p-2 text-[#d4d4d4] hover:bg-white/5 lg:hidden"
      >
        <Menu className="size-5" />
      </button>

      <div className="flex shrink-0 items-center gap-2">
        <TierXLogo className="size-6 text-primary" />
        <span className="text-xl font-bold tracking-tight">TierX</span>
      </div>

      <div className="ml-auto flex items-center gap-3 sm:gap-4">
        <HealthBadge />

        <div className="hidden h-8 w-px bg-[#525252] sm:block" />

        <div className="hidden min-w-0 rounded-lg bg-card px-3 py-2 sm:block">
          <p className="truncate text-sm text-foreground">{user?.email}</p>
          <p className="text-xs text-muted-foreground">
            {user?.role?.replace(/_/g, " ")}
          </p>
        </div>
      </div>
    </header>
  );
}
