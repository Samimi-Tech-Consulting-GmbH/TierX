export function executionDebugHome(tenantId: string, platformAdmin = false) {
  return platformAdmin
    ? "/dashboard/admin/debug"
    : `/dashboard/${encodeURIComponent(tenantId)}/debug`;
}

export function executionDebugHref(
  tenantId: string,
  runId: string,
  platformAdmin = false,
) {
  return platformAdmin
    ? `/dashboard/admin/debug/runs/${encodeURIComponent(tenantId)}/${encodeURIComponent(runId)}`
    : `${executionDebugHome(tenantId)}/runs/${encodeURIComponent(runId)}`;
}
