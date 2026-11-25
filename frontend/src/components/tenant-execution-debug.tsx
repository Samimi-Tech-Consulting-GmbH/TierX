"use client";
import { WorkflowExecutionIndex } from "./workflow-execution-index";

export function TenantExecutionDebug({ tenantId }: { tenantId: string }) {
  return <WorkflowExecutionIndex key={tenantId} tenantId={tenantId} />;
}
