import {
  getMyAlert,
  getMyDeadLetter,
  getMyPipelineHealthSummary,
  getTenantAlert,
  getTenantDeadLetter,
  getTenantPipelineHealthSummary,
  listMyAlerts,
  listMyDeadLetters,
  listTenantAlerts,
  listTenantDeadLetters,
  getTenantAlertStats,
} from "@/lib/api";

export type TenantScope = "admin" | "tenant";

export function scopedApi(scope: TenantScope) {
  const admin = scope === "admin";
  return {
    listAlerts: (...args: Parameters<typeof listTenantAlerts>) =>
      (admin ? listTenantAlerts : listMyAlerts)(...args),
    getAlert: (...args: Parameters<typeof getTenantAlert>) =>
      (admin ? getTenantAlert : getMyAlert)(...args),
    listDeadLetters: (...args: Parameters<typeof listTenantDeadLetters>) =>
      (admin ? listTenantDeadLetters : listMyDeadLetters)(...args),
    getDeadLetter: (...args: Parameters<typeof getTenantDeadLetter>) =>
      (admin ? getTenantDeadLetter : getMyDeadLetter)(...args),
    pipelineHealth: (
      ...args: Parameters<typeof getTenantPipelineHealthSummary>
    ) =>
      (admin ? getTenantPipelineHealthSummary : getMyPipelineHealthSummary)(
        ...args,
      ),
    alertStats: (...args: Parameters<typeof getTenantAlertStats>) =>
      getTenantAlertStats(...args),
  };
}

export function scopedRoutes(scope: TenantScope, tenantId: string) {
  const base =
    scope === "admin"
      ? `/dashboard/admin/tenants/${tenantId}`
      : `/dashboard/${tenantId}`;
  return {
    home: base,
    alerts: `${base}/alerts`,
    clusters: `${base}/clusters`,
    deadLetters:
      scope === "admin"
        ? `${base}/dead-letters`
        : `${base}/alerts/dead-letters`,
  };
}
