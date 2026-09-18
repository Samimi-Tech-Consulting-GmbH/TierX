"use client";

import { useParams } from "next/navigation";

import { AlertsDashboardView } from "@/components/alerts-dashboard-view";

export default function AdminAlertsDashboardPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <AlertsDashboardView tenantId={tenantId} scope="admin" />;
}
