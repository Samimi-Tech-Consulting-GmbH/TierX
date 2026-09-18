"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function TenantClusterDetailPage() {
  const router = useRouter();
  const { tenantId, clusterId } = useParams<{
    tenantId: string;
    clusterId: string;
  }>();

  useEffect(() => {
    router.replace(
      `/dashboard/${tenantId}/clusters?cluster=${encodeURIComponent(clusterId)}`,
    );
  }, [router, tenantId, clusterId]);

  return null;
}
