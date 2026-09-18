"use client";

import { useParams } from "next/navigation";

import { DeadLettersView } from "@/components/dead-letters-view";

export default function TenantDeadLettersPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <DeadLettersView tenantId={tenantId} scope="tenant" />;
}
