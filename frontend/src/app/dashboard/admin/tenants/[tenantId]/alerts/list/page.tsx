"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function LegacyAdminAlertListRedirect() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/dashboard/admin/tenants/${tenantId}/alerts`);
  }, [router, tenantId]);

  return <p className="text-sm text-muted-foreground">Opening alerts…</p>;
}
