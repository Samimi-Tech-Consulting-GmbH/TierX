import { TenantExecutionDebug } from "@/components/tenant-execution-debug";
export default async function Page({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = await params;
  return <TenantExecutionDebug key={tenantId} tenantId={tenantId} />;
}
