"use client";

import { useParams } from "next/navigation";

import { KnowledgeBaseView } from "@/components/knowledge-base-view";


export default function TenantKnowledgeBasePage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <KnowledgeBaseView tenantId={tenantId} />;
}
