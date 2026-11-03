import { WorkflowRunView } from "@/components/workflow-run-view";
export default async function Page({ params }: { params: Promise<{ tenantId: string; runId: string }> }) {
  const { tenantId, runId } = await params;
  return <WorkflowRunView tenantId={tenantId} runId={runId} />;
}
