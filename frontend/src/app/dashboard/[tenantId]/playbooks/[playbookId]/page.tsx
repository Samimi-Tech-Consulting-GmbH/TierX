"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function PlaybookDetailRedirect() {
  const router = useRouter();
  const { tenantId, playbookId } = useParams<{
    tenantId: string;
    playbookId: string;
  }>();

  useEffect(() => {
    router.replace(
      `/dashboard/${tenantId}/playbooks?playbook=${encodeURIComponent(playbookId)}`,
    );
  }, [router, tenantId, playbookId]);

  return null;
}
