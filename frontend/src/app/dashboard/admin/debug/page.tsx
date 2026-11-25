"use client";
import { WorkflowExecutionIndex } from "@/components/workflow-execution-index";
import { ALL_TENANTS, useSelectedTenant } from "@/lib/selected-tenant";

export default function DebugPage() {
  const { selectedTenantId, loading } = useSelectedTenant();
  if (loading) return <p role="status">Loading tenant scope…</p>;
  const tenantId = selectedTenantId && selectedTenantId !== ALL_TENANTS ? selectedTenantId : undefined;
  return <WorkflowExecutionIndex key={tenantId || "all"} tenantId={tenantId} platformAdmin />;
}
