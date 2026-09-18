"use client";

import { ClusterListView } from "@/components/cluster-list-view";

export default function AllTenantsClustersPage() {
  return <ClusterListView tenantId={null} homeHref="/dashboard/admin" />;
}
