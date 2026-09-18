"use client";

import { useParams } from "next/navigation";
import { ClusterListView } from "@/components/cluster-list-view";

export default function AdminClustersPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return (
    <ClusterListView
      tenantId={tenantId}
      homeHref={`/dashboard/admin`}
      alertBase={`/dashboard/admin/tenants/${tenantId}/alerts`}
    />
  );
}
