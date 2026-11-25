import { redirect } from "next/navigation";
import { executionDebugHref } from "@/lib/execution-navigation";
export default async function Page({
  params,
}: {
  params: Promise<{ tenantId: string; runId: string }>;
}) {
  const { tenantId, runId } = await params;
  redirect(executionDebugHref(tenantId, runId));
}
