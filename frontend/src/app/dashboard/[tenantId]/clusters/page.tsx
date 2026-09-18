"use client";

import { useParams } from "next/navigation";
import { ClusterListView } from "@/components/cluster-list-view";

export default function TenantClustersPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return (
    <ClusterListView
      tenantId={tenantId}
      homeHref={`/dashboard/${tenantId}`}
      alertBase={`/dashboard/${tenantId}/alerts`}
    />
  );
}
