"use client";

import { useParams } from "next/navigation";

import { DeadLetterDetailView } from "@/components/dead-letter-detail-view";

export default function TenantDeadLetterDetailPage() {
  const { tenantId, deadLetterId } = useParams<{
    tenantId: string;
    deadLetterId: string;
  }>();
  return (
    <DeadLetterDetailView
      tenantId={tenantId}
      deadLetterId={deadLetterId}
      scope="tenant"
    />
  );
}
