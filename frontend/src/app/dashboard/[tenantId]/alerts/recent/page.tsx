"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function LegacyTenantRecentAlertsRedirect() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/dashboard/${tenantId}/alerts`);
  }, [router, tenantId]);

  return <p className="text-sm text-muted-foreground">Opening alerts…</p>;
}
