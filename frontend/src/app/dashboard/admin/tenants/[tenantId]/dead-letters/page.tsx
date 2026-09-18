"use client";

import { useParams } from "next/navigation";

import { DeadLettersView } from "@/components/dead-letters-view";

export default function AdminTenantDeadLettersPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <DeadLettersView tenantId={tenantId} scope="admin" />;
}
