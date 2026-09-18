"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Bell, BookOpen, FileCode2, Network, Settings } from "lucide-react";

import { useAuth } from "@/lib/auth";
import { UserRole } from "@/lib/types";
import { NavCard, type NavCardItem } from "@/components/dashboard/nav-card";
import { PlatformKpiRow } from "@/components/dashboard/platform-kpi-row";
import { useTenantDashboard } from "@/lib/use-tenant-dashboard";

export default function TenantDashboardHomePage() {
  const params = useParams<{ tenantId: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const tenantId = params.tenantId;
  const dashboard = useTenantDashboard(tenantId);

  useEffect(() => {
    if (!user) return;
    if (user.role === UserRole.PLATFORM_ADMIN) return;
    if (user.tenant_id !== tenantId) {
      router.replace(
        user.tenant_id ? `/dashboard/${user.tenant_id}` : "/login",
      );
    }
  }, [user, tenantId, router]);

  if (
    user &&
    user.role !== UserRole.PLATFORM_ADMIN &&
    user.tenant_id !== tenantId
  ) {
    return null;
  }

  const cards: NavCardItem[] = [
    {
      href: `/dashboard/${tenantId}/alerts`,
      title: "Alerts Management",
      description: "Inspect and analyse incoming security alerts.",
      icon: Bell,
    },
    {
      href: `/dashboard/${tenantId}/clusters`,
      title: "Cluster Analysis",
      description:
        "Analyse alert clusters and identify complex attack patterns.",
      icon: Network,
    },
    {
      href: `/dashboard/${tenantId}/playbooks`,
      title: "Playbooks",
      description: "Upload YAML definitions and manage playbook revisions.",
      icon: BookOpen,
    },
    {
      href: `/dashboard/${tenantId}/schema-registry`,
      title: "Schema Registry",
      description:
        "Versioned ECS field mappings and critical fields per alert type.",
      icon: FileCode2,
    },
  ];

  if (user?.role === UserRole.TENANT_ADMIN) {
    cards.push({
      href: `/dashboard/${tenantId}/settings`,
      title: "Tenant settings",
      description: "Contact details and tenant-level configuration overrides.",
      icon: Settings,
    });
  }

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">Tenant dashboard</h1>
        <p className="break-all font-mono text-xs text-muted-foreground">
          {tenantId}
        </p>
      </div>

      <PlatformKpiRow
        summary={dashboard.summary}
        loading={dashboard.loading}
        error={dashboard.error}
      />

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => (
          <NavCard key={card.href} {...card} />
        ))}
      </div>
    </div>
  );
}
