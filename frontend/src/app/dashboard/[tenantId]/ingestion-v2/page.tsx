"use client";
import { useParams } from "next/navigation";
import { WorkflowBuilder } from "@/components/workflow-builder";
export default function Page() {
  const { tenantId } = useParams<{ tenantId: string }>();
  return <WorkflowBuilder tenantId={tenantId} />;
}
