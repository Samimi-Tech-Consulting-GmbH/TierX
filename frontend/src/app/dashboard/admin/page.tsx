"use client";

import { Bell, Book, Building2, Database, Network } from "lucide-react";

import { useAuth } from "@/lib/auth";
import { usePlatformDashboard } from "@/lib/use-platform-dashboard";
import { AlertActivityCard } from "@/components/dashboard/alert-activity-card";
import { PlatformKpiRow } from "@/components/dashboard/platform-kpi-row";
import { RecentActivityCard } from "@/components/dashboard/recent-activity-card";
import { SystemStatusCard } from "@/components/dashboard/system-status-card";
import { NavCard, type NavCardItem } from "@/components/dashboard/nav-card";

const CARDS: NavCardItem[] = [
  {
    href: "/dashboard/admin/alerts",
    title: "Alerts Management",
    description: "Inspect and analyse incoming security alerts across tenants.",
    icon: Bell,
  },
  {
    href: "/dashboard/admin/clusters",
    title: "Cluster Analysis",
    description: "Analyse alert clusters and identify complex attack patterns.",
    icon: Network,
  },
  {
    href: "/dashboard/admin/schema-registry",
    title: "Schema Registry",
    description:
      "Configure and manage the data structures for your security data.",
    icon: Database,
  },
  {
    href: "/dashboard/admin/playbooks",
    title: "Playbook Management",
    description: "Manage analysis prompts and playbook configuration.",
    icon: Book,
  },
  {
    href: "/dashboard/admin/tenants",
    title: "Tenant Management",
    description: "Create, suspend and configure organisations.",
    icon: Building2,
  },
];

function firstNameOf(email: string | undefined): string | null {
  const part = email?.split("@")[0]?.split(/[._-]+/)[0];
  return part ? part.charAt(0).toUpperCase() + part.slice(1) : null;
}

export default function PlatformAdminDashboardPage() {
  const { user } = useAuth();
  const { summary, loading, error } = usePlatformDashboard();
  const firstName = firstNameOf(user?.email);

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">
          Dashboard Overview
        </h1>
        <p className="text-base text-muted-foreground">
          {firstName ? `Welcome back, ${firstName}.` : "Welcome back."} Here is
          your central overview of all key functions and metrics.
        </p>
      </div>

      <PlatformKpiRow summary={summary} loading={loading} error={error} />

      {/* Every metric card sits here, above the navigation grid. */}
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <AlertActivityCard
          className="xl:col-span-2"
          summary={summary}
          loading={loading}
          error={error}
        />
        <SystemStatusCard />
        <RecentActivityCard summary={summary} loading={loading} error={error} />
      </div>

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {CARDS.map((card) => (
          <NavCard key={card.href} {...card} />
        ))}
      </div>
    </div>
  );
}
