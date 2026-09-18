"use client";

import { useParams } from "next/navigation";

import { AlertDetailView } from "@/components/alert-detail-view";

export default function TenantAlertDetailPage() {
  const { tenantId, alertId } = useParams<{
    tenantId: string;
    alertId: string;
  }>();
  return (
    <AlertDetailView tenantId={tenantId} alertId={alertId} scope="tenant" />
  );
}
