import type {
  TenantCreate,
  TenantUpdate,
  TenantStatusUpdate,
  TenantDocument,
  TenantStatus,
  PipelineHealthSummary,
  TenantSelfServiceSettingsPayload,
  DeadLetterPage,
  DeadLetterRecord,
  AlertDocument,
  AlertPage,
  UserDocument,
  UserCreatePayload,
  TenantUserCreatePayload,
  PlaybookDocument,
  PlaybookListItem,
  PlaybookReplace,
  PlaybookVersionSummary,
  AlertTypeSchemaDocument,
  AlertTypeSchemaListResponse,
  ProcessingTracePage,
  ProcessingTraceDetail,
  AnalysisRunPage,
  AnalysisRetryResponse,
  ClusterDocument,
  ClusterPage,
  PlatformHealth,
  PlatformDashboardSummary,
  TenantDashboardSummary,
  AlertStats,
  PlaybookStats,
  TenantPage,
  PlatformAlert,
  PlatformCluster,
  PlatformPage,
  PlatformPlaybook,
  PlatformSchema,
  WebhookSecretMetadata,
  WebhookSecretCreated,
  JiraSiteConnection,
  JiraSiteConnectionCreated,
  JiraSiteConnectionCreate,
  JiraProjectRoute,
  JiraProjectRouteWrite,
  EnrichmentAction,
  EnrichmentActionCreated,
  EnrichmentActionPage,
  EnrichmentActionWrite,
  KnowledgeBaseDocument,
  KnowledgeBaseDocumentPage,
  KnowledgeBaseChunk,
  KnowledgeBaseSearchResponse,
} from "./types";

import { readToken, clearToken } from "./auth";

const API_BASE =
  process.env.NEXT_PUBLIC_TIERX_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";

class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    /** Original API JSON body shape when structured (e.g. playbook validation). */
    public raw?: unknown,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function getToken(): string | null {
  return readToken();
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }

  if (!res.ok) {
    await parseFailedResponse(res);
  }

  return res.json();
}

async function parseFailedResponse(res: Response): Promise<never> {
  const body = await res.json().catch(() => ({ detail: res.statusText }));
  let detailStr: string =
    typeof body.detail === "string" ? body.detail : "Unknown error";
  if (
    body.detail &&
    typeof body.detail === "object" &&
    Array.isArray((body.detail as { errors?: unknown }).errors)
  ) {
    const errs = (
      body.detail as { errors: { loc?: unknown[]; msg?: string }[] }
    ).errors;
    detailStr = errs
      .map((e) => `${(e.loc ?? []).join(".")}: ${e.msg ?? "invalid"}`)
      .join("; ");
  }
  throw new ApiError(res.status, detailStr, body);
}

async function requestWithoutJsonBody<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) {
    await parseFailedResponse(res);
  }
  return res.json();
}

async function requestNoContent(
  path: string,
  options: RequestInit = {},
): Promise<void> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) await parseFailedResponse(res);
}

async function requestBlob(
  path: string,
  options: RequestInit = {},
): Promise<Blob> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }
  if (!res.ok) await parseFailedResponse(res);
  return res.blob();
}

// --- Tenant Knowledge Base ---

export async function listKnowledgeBaseDocuments(
  tenantId: string,
  params?: { skip?: number; limit?: number },
): Promise<KnowledgeBaseDocumentPage> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  const qs = query.toString();
  return request<KnowledgeBaseDocumentPage>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/documents${qs ? `?${qs}` : ""}`,
  );
}

export async function uploadKnowledgeBaseDocument(
  tenantId: string,
  file: File,
): Promise<KnowledgeBaseDocument> {
  const form = new FormData();
  form.append("file", file);
  return requestWithoutJsonBody<KnowledgeBaseDocument>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/documents`,
    { method: "POST", body: form },
  );
}

export async function downloadKnowledgeBaseDocument(
  tenantId: string,
  documentId: string,
): Promise<Blob> {
  return requestBlob(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/documents/${encodeURIComponent(documentId)}/download`,
  );
}

export async function deleteKnowledgeBaseDocument(
  tenantId: string,
  documentId: string,
): Promise<void> {
  return requestNoContent(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );
}

export async function getKnowledgeBaseDocument(
  tenantId: string,
  documentId: string,
): Promise<KnowledgeBaseDocument> {
  return request<KnowledgeBaseDocument>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/documents/${encodeURIComponent(documentId)}`,
  );
}

export async function listKnowledgeBaseChunks(
  tenantId: string,
  documentId: string,
): Promise<{
  items: KnowledgeBaseChunk[];
  total: number;
  skip: number;
  limit: number;
}> {
  return request<{
    items: KnowledgeBaseChunk[];
    total: number;
    skip: number;
    limit: number;
  }>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/documents/${encodeURIComponent(documentId)}/chunks?limit=200`,
  );
}

export async function reprocessKnowledgeBaseDocument(
  tenantId: string,
  documentId: string,
): Promise<KnowledgeBaseDocument> {
  return request<KnowledgeBaseDocument>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/documents/${encodeURIComponent(documentId)}/reprocess`,
    { method: "POST" },
  );
}

export async function searchKnowledgeBase(
  tenantId: string,
  query: string,
  topK = 5,
  retrievalMode: "deterministic" | "hybrid" = "deterministic",
): Promise<KnowledgeBaseSearchResponse> {
  return request<KnowledgeBaseSearchResponse>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/knowledge-base/search`,
    { method: "POST", body: JSON.stringify({ query, top_k: topK, retrieval_mode: retrievalMode }) },
  );
}

// --- Platform-managed enrichment actions ---

export async function listEnrichmentActions(): Promise<EnrichmentActionPage> {
  return request<EnrichmentActionPage>(
    "/api/v1/admin/enrichment-actions?limit=200",
  );
}

export async function createEnrichmentAction(
  body: EnrichmentActionWrite,
): Promise<EnrichmentActionCreated> {
  return request<EnrichmentActionCreated>("/api/v1/admin/enrichment-actions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateEnrichmentAction(
  actionCode: string,
  body: Omit<EnrichmentActionWrite, "action_code">,
): Promise<EnrichmentAction> {
  return request<EnrichmentAction>(
    `/api/v1/admin/enrichment-actions/${encodeURIComponent(actionCode)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}

export async function rotateEnrichmentActionSecret(
  actionCode: string,
): Promise<EnrichmentActionCreated> {
  return request<EnrichmentActionCreated>(
    `/api/v1/admin/enrichment-actions/${encodeURIComponent(actionCode)}/rotate`,
    { method: "POST" },
  );
}

export async function deleteEnrichmentAction(
  actionCode: string,
): Promise<EnrichmentAction> {
  return request<EnrichmentAction>(
    `/api/v1/admin/enrichment-actions/${encodeURIComponent(actionCode)}`,
    { method: "DELETE" },
  );
}

export async function listTenantEnrichmentActions(
  tenantId: string,
): Promise<EnrichmentAction[]> {
  return request<EnrichmentAction[]>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/enrichment-actions`,
  );
}

// --- Platform Jira integrations ---

export async function listJiraSiteConnections(): Promise<JiraSiteConnection[]> {
  return request<JiraSiteConnection[]>("/api/v1/admin/integrations/jira");
}

export async function createJiraSiteConnection(
  body: JiraSiteConnectionCreate,
): Promise<JiraSiteConnectionCreated> {
  return request<JiraSiteConnectionCreated>("/api/v1/admin/integrations/jira", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function rotateJiraSiteConnection(
  integrationId: string,
): Promise<JiraSiteConnectionCreated> {
  return request<JiraSiteConnectionCreated>(
    `/api/v1/admin/integrations/jira/${encodeURIComponent(integrationId)}/rotate`,
    { method: "POST" },
  );
}

export async function revokeJiraSiteConnection(
  integrationId: string,
): Promise<JiraSiteConnection> {
  return request<JiraSiteConnection>(
    `/api/v1/admin/integrations/jira/${encodeURIComponent(integrationId)}`,
    { method: "DELETE" },
  );
}

export async function listJiraProjectRoutes(
  integrationId: string,
): Promise<JiraProjectRoute[]> {
  return request<JiraProjectRoute[]>(
    `/api/v1/admin/integrations/jira/${encodeURIComponent(integrationId)}/routes`,
  );
}

export async function createJiraProjectRoute(
  integrationId: string,
  body: JiraProjectRouteWrite,
): Promise<JiraProjectRoute> {
  return request<JiraProjectRoute>(
    `/api/v1/admin/integrations/jira/${encodeURIComponent(integrationId)}/routes`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function updateJiraProjectRoute(
  integrationId: string,
  routeId: string,
  body: JiraProjectRouteWrite,
): Promise<JiraProjectRoute> {
  return request<JiraProjectRoute>(
    `/api/v1/admin/integrations/jira/${encodeURIComponent(integrationId)}/routes/${encodeURIComponent(routeId)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}

export async function setJiraProjectRouteEnabled(
  integrationId: string,
  routeId: string,
  enabled: boolean,
): Promise<JiraProjectRoute> {
  return request<JiraProjectRoute>(
    `/api/v1/admin/integrations/jira/${encodeURIComponent(integrationId)}/routes/${encodeURIComponent(routeId)}/state`,
    { method: "PATCH", body: JSON.stringify({ enabled }) },
  );
}

export async function deleteJiraProjectRoute(
  integrationId: string,
  routeId: string,
): Promise<void> {
  return requestNoContent(
    `/api/v1/admin/integrations/jira/${encodeURIComponent(integrationId)}/routes/${encodeURIComponent(routeId)}`,
    { method: "DELETE" },
  );
}

export async function createTenant(
  data: TenantCreate,
): Promise<TenantDocument> {
  return request<TenantDocument>("/api/v1/admin/tenants", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function listTenants(params?: {
  skip?: number;
  limit?: number;
  status?: TenantStatus;
  search?: string;
}): Promise<TenantDocument[]> {
  const query = new URLSearchParams();
  if (params?.skip) query.set("skip", String(params.skip));
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.status) query.set("status", params.status);
  if (params?.search) query.set("search", params.search);

  const qs = query.toString();
  return request<TenantDocument[]>(
    `/api/v1/admin/tenants${qs ? `?${qs}` : ""}`,
  );
}

export async function listTenantPage(params?: {
  skip?: number;
  limit?: number;
  status?: TenantStatus;
  search?: string;
}): Promise<TenantPage> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.status) query.set("status", params.status);
  if (params?.search) query.set("search", params.search);
  const qs = query.toString();
  return request<TenantPage>(`/api/v1/admin/tenants/page${qs ? `?${qs}` : ""}`);
}

export async function getPlatformDashboardSummary(): Promise<PlatformDashboardSummary> {
  return request<PlatformDashboardSummary>("/api/v1/admin/dashboard/summary");
}

export async function getTenantDashboardSummary(
  tenantId: string,
): Promise<TenantDashboardSummary> {
  return request<TenantDashboardSummary>(
    `/api/v1/tenants/${tenantId}/dashboard/summary`,
  );
}

export async function getTenant(tenantId: string): Promise<TenantDocument> {
  return request<TenantDocument>(`/api/v1/admin/tenants/${tenantId}`);
}

export async function updateTenant(
  tenantId: string,
  data: TenantUpdate,
): Promise<TenantDocument> {
  return request<TenantDocument>(`/api/v1/admin/tenants/${tenantId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function updateTenantStatus(
  tenantId: string,
  data: TenantStatusUpdate,
): Promise<TenantDocument> {
  return request<TenantDocument>(`/api/v1/admin/tenants/${tenantId}/status`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function getAdminTenantOnboardingStatus(
  tenantId: string,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/api/v1/admin/tenants/${tenantId}/onboarding-status`,
  );
}

export async function getTenantPipelineHealthSummary(
  tenantId: string,
): Promise<PipelineHealthSummary> {
  return request<PipelineHealthSummary>(
    `/api/v1/admin/tenants/${tenantId}/pipeline-health-summary`,
  );
}

export async function listTenantDeadLetters(
  tenantId: string,
  params?: { skip?: number; limit?: number; since_hours?: number },
): Promise<DeadLetterPage> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.since_hours != null)
    query.set("since_hours", String(params.since_hours));
  const qs = query.toString();
  return request<DeadLetterPage>(
    `/api/v1/admin/tenants/${tenantId}/dead-letters${qs ? `?${qs}` : ""}`,
  );
}

export async function getTenantDeadLetter(
  tenantId: string,
  deadLetterId: string,
): Promise<DeadLetterRecord> {
  return request<DeadLetterRecord>(
    `/api/v1/admin/tenants/${tenantId}/dead-letters/${deadLetterId}`,
  );
}

export async function getTenantOnboardingSelfService(
  tenantId: string,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/api/v1/tenants/${tenantId}/onboarding-status`,
  );
}

export async function updateTenantSettingsSelfService(
  tenantId: string,
  data: TenantSelfServiceSettingsPayload,
): Promise<TenantDocument> {
  return request<TenantDocument>(`/api/v1/tenants/${tenantId}/settings`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// --- Tenant-scoped info ---

export async function getMyTenant(tenantId: string): Promise<TenantDocument> {
  return request<TenantDocument>(`/api/v1/tenants/${tenantId}`);
}

// --- Users (Platform Admin) ---

export async function listAllUsers(params?: {
  skip?: number;
  limit?: number;
  tenant_id?: string;
}): Promise<UserDocument[]> {
  const query = new URLSearchParams();
  if (params?.skip) query.set("skip", String(params.skip));
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.tenant_id) query.set("tenant_id", params.tenant_id);
  const qs = query.toString();
  return request<UserDocument[]>(`/api/v1/admin/users${qs ? `?${qs}` : ""}`);
}

export async function createUserAdmin(
  data: UserCreatePayload,
): Promise<UserDocument> {
  return request<UserDocument>("/api/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// --- Users (Tenant-scoped) ---

export async function listTenantUsers(
  tenantId: string,
): Promise<UserDocument[]> {
  return request<UserDocument[]>(`/api/v1/tenants/${tenantId}/users`);
}

export async function createTenantUser(
  tenantId: string,
  data: TenantUserCreatePayload,
): Promise<UserDocument> {
  return request<UserDocument>(`/api/v1/tenants/${tenantId}/users`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// --- Playbooks ---

export async function listPlaybooks(
  tenantId: string,
  params?: {
    skip?: number;
    limit?: number;
    is_active?: boolean;
    alert_type?: string;
  },
): Promise<PlaybookListItem[]> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.is_active !== undefined) {
    query.set("is_active", String(params.is_active));
  }
  if (params?.alert_type) query.set("alert_type", params.alert_type);
  const qs = query.toString();
  return request<PlaybookListItem[]>(
    `/api/v1/tenants/${tenantId}/playbooks${qs ? `?${qs}` : ""}`,
  );
}

export async function getPlaybookStats(
  tenantId: string,
): Promise<PlaybookStats> {
  return request<PlaybookStats>(`/api/v1/tenants/${tenantId}/playbooks/stats`);
}

export async function getPlaybook(
  tenantId: string,
  playbookId: string,
): Promise<PlaybookDocument> {
  return request<PlaybookDocument>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}`,
  );
}

export async function listPlaybookVersions(
  tenantId: string,
  playbookId: string,
): Promise<PlaybookVersionSummary[]> {
  return request<PlaybookVersionSummary[]>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}/versions`,
  );
}

export async function createPlaybookFromYaml(
  tenantId: string,
  name: string,
  file: File,
): Promise<PlaybookDocument> {
  const form = new FormData();
  form.append("name", name);
  form.append("file", file);
  return requestWithoutJsonBody<PlaybookDocument>(
    `/api/v1/tenants/${tenantId}/playbooks`,
    { method: "POST", body: form },
  );
}

export async function appendPlaybookRevisionFromYaml(
  tenantId: string,
  playbookId: string,
  name: string,
  file: File,
): Promise<PlaybookDocument> {
  const form = new FormData();
  form.append("name", name);
  form.append("file", file);
  return requestWithoutJsonBody<PlaybookDocument>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}/yaml`,
    { method: "PUT", body: form },
  );
}

export async function replacePlaybook(
  tenantId: string,
  playbookId: string,
  data: PlaybookReplace,
): Promise<PlaybookDocument> {
  return request<PlaybookDocument>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}`,
    {
      method: "PUT",
      body: JSON.stringify(data),
    },
  );
}

export async function deletePlaybook(
  tenantId: string,
  playbookId: string,
): Promise<PlaybookDocument> {
  return request<PlaybookDocument>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}`,
    { method: "DELETE" },
  );
}

export async function getTenantWebhookSecret(
  tenantId: string,
): Promise<WebhookSecretMetadata> {
  return request<WebhookSecretMetadata>(
    `/api/v1/tenants/${tenantId}/webhook-signing-secret`,
  );
}

export async function rotateTenantWebhookSecret(
  tenantId: string,
): Promise<WebhookSecretCreated> {
  return request<WebhookSecretCreated>(
    `/api/v1/tenants/${tenantId}/webhook-signing-secret`,
    { method: "POST" },
  );
}

export async function deleteTenantWebhookSecret(
  tenantId: string,
): Promise<WebhookSecretMetadata> {
  return request<WebhookSecretMetadata>(
    `/api/v1/tenants/${tenantId}/webhook-signing-secret`,
    { method: "DELETE" },
  );
}

export async function getPlaybookWebhookSecret(
  tenantId: string,
  playbookId: string,
): Promise<WebhookSecretMetadata> {
  return request<WebhookSecretMetadata>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}/webhook-signing-secret`,
  );
}

export async function rotatePlaybookWebhookSecret(
  tenantId: string,
  playbookId: string,
): Promise<WebhookSecretCreated> {
  return request<WebhookSecretCreated>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}/webhook-signing-secret`,
    { method: "POST" },
  );
}

export async function deletePlaybookWebhookSecret(
  tenantId: string,
  playbookId: string,
): Promise<WebhookSecretMetadata> {
  return request<WebhookSecretMetadata>(
    `/api/v1/tenants/${tenantId}/playbooks/${playbookId}/webhook-signing-secret`,
    { method: "DELETE" },
  );
}

// --- Alert-type schema registry (tenant DB) ---

export async function listAlertTypeSchemas(
  tenantId: string,
  params?: {
    skip?: number;
    limit?: number;
    is_active?: boolean;
    alert_type?: string;
    q?: string;
  },
): Promise<AlertTypeSchemaListResponse> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.is_active !== undefined) {
    query.set("is_active", String(params.is_active));
  }
  if (params?.alert_type) query.set("alert_type", params.alert_type);
  if (params?.q) query.set("q", params.q);
  const qs = query.toString();
  return request<AlertTypeSchemaListResponse>(
    `/api/v1/tenants/${tenantId}/schema-registry${qs ? `?${qs}` : ""}`,
  );
}

export async function getAlertTypeSchemaById(
  tenantId: string,
  schemaId: string,
): Promise<AlertTypeSchemaDocument> {
  return request<AlertTypeSchemaDocument>(
    `/api/v1/tenants/${tenantId}/schema-registry/by-id/${encodeURIComponent(schemaId)}`,
  );
}

export async function listAlertTypeSchemaHistory(
  tenantId: string,
  alertType: string,
): Promise<AlertTypeSchemaDocument[]> {
  const at = encodeURIComponent(alertType);
  return request<AlertTypeSchemaDocument[]>(
    `/api/v1/tenants/${tenantId}/schema-registry/${at}/history`,
  );
}

export async function createAlertTypeSchemaFromYaml(
  tenantId: string,
  file: File,
  playbookId?: string | null,
): Promise<AlertTypeSchemaDocument> {
  const form = new FormData();
  form.append("file", file);
  if (playbookId) {
    form.append("playbook_id", playbookId);
  }
  return requestWithoutJsonBody<AlertTypeSchemaDocument>(
    `/api/v1/tenants/${tenantId}/schema-registry`,
    { method: "POST", body: form },
  );
}

export async function activateAlertTypeSchema(
  tenantId: string,
  alertType: string,
  schemaId: string,
): Promise<AlertTypeSchemaDocument> {
  const at = encodeURIComponent(alertType);
  return request<AlertTypeSchemaDocument>(
    `/api/v1/tenants/${tenantId}/schema-registry/${at}/${schemaId}/activate`,
    { method: "POST" },
  );
}

// --- Admin alerts ---

export async function listTenantAlerts(
  tenantId: string,
  params?: { skip?: number; limit?: number; since_hours?: number; q?: string },
): Promise<AlertPage> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.since_hours != null)
    query.set("since_hours", String(params.since_hours));
  if (params?.q) query.set("q", params.q);
  const qs = query.toString();
  return request<AlertPage>(
    `/api/v1/admin/tenants/${tenantId}/alerts${qs ? `?${qs}` : ""}`,
  );
}

export async function getTenantAlert(
  tenantId: string,
  alertId: string,
): Promise<AlertDocument> {
  return request<AlertDocument>(
    `/api/v1/admin/tenants/${tenantId}/alerts/${alertId}`,
  );
}

// --- Tenant-scoped alerts ---

export async function getMyPipelineHealthSummary(
  tenantId: string,
): Promise<PipelineHealthSummary> {
  return request<PipelineHealthSummary>(
    `/api/v1/tenants/${tenantId}/pipeline-health-summary`,
  );
}

export async function listMyAlerts(
  tenantId: string,
  params?: { skip?: number; limit?: number; since_hours?: number; q?: string },
): Promise<AlertPage> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.since_hours != null)
    query.set("since_hours", String(params.since_hours));
  if (params?.q) query.set("q", params.q);
  const qs = query.toString();
  return request<AlertPage>(
    `/api/v1/tenants/${tenantId}/alerts${qs ? `?${qs}` : ""}`,
  );
}

export async function getTenantAlertStats(
  tenantId: string,
  params?: { since_hours?: number; q?: string },
): Promise<AlertStats> {
  return request<AlertStats>(
    `/api/v1/tenants/${tenantId}/alerts/stats${platformQuery(params)}`,
  );
}

export async function getMyAlert(
  tenantId: string,
  alertId: string,
): Promise<AlertDocument> {
  return request<AlertDocument>(
    `/api/v1/tenants/${tenantId}/alerts/${alertId}`,
  );
}

// --- Analysis and clusters ---

export async function listAlertAnalysisRuns(
  tenantId: string,
  alertId: string,
): Promise<AnalysisRunPage> {
  return request<AnalysisRunPage>(
    `/api/v1/tenants/${tenantId}/alerts/${encodeURIComponent(alertId)}/analysis/runs`,
  );
}

export async function retryAlertAnalysis(
  tenantId: string,
  alertId: string,
): Promise<AnalysisRetryResponse> {
  return request<AnalysisRetryResponse>(
    `/api/v1/tenants/${tenantId}/alerts/${encodeURIComponent(alertId)}/analysis/retry`,
    { method: "POST" },
  );
}

export async function listClusters(
  tenantId: string,
  params?: {
    skip?: number;
    limit?: number;
    status?: string;
    created_after?: string;
    q?: string;
  },
): Promise<ClusterPage> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.status) query.set("status", params.status);
  if (params?.created_after) query.set("created_after", params.created_after);
  if (params?.q) query.set("q", params.q);
  const qs = query.toString();
  return request<ClusterPage>(
    `/api/v1/tenants/${tenantId}/clusters${qs ? `?${qs}` : ""}`,
  );
}

export async function getCluster(
  tenantId: string,
  clusterId: string,
): Promise<ClusterDocument> {
  return request<ClusterDocument>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}`,
  );
}

export async function getClusterAlerts(
  tenantId: string,
  clusterId: string,
  params?: { skip?: number; limit?: number },
): Promise<{ items: AlertDocument[]; total: number }> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  const qs = query.toString();
  return request<{ items: AlertDocument[]; total: number }>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/alerts${qs ? `?${qs}` : ""}`,
  );
}

export async function getClusterSummaryHistory(
  tenantId: string,
  clusterId: string,
): Promise<{ items: import("./types").AnalysisResult[] }> {
  return request<{ items: import("./types").AnalysisResult[] }>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/summary/history`,
  );
}

export async function listClusterAnalysisRuns(
  tenantId: string,
  clusterId: string,
): Promise<AnalysisRunPage> {
  return request<AnalysisRunPage>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/analysis/runs`,
  );
}

export async function retryClusterAnalysis(
  tenantId: string,
  clusterId: string,
): Promise<AnalysisRetryResponse> {
  return request<AnalysisRetryResponse>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/analysis/retry`,
    { method: "POST" },
  );
}

export async function updateClusterStatus(
  tenantId: string,
  clusterId: string,
  status: string,
): Promise<ClusterDocument> {
  return request<ClusterDocument>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/status`,
    { method: "PATCH", body: JSON.stringify({ status }) },
  );
}

export async function assignCluster(
  tenantId: string,
  clusterId: string,
  assignedTo: string | null,
): Promise<ClusterDocument> {
  return request<ClusterDocument>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/assign`,
    { method: "PATCH", body: JSON.stringify({ assigned_to: assignedTo }) },
  );
}

export async function setClusterVerdict(
  tenantId: string,
  clusterId: string,
  verdict: string,
): Promise<ClusterDocument> {
  return request<ClusterDocument>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/verdict`,
    { method: "PATCH", body: JSON.stringify({ verdict }) },
  );
}

export async function addClusterNote(
  tenantId: string,
  clusterId: string,
  note: string,
): Promise<ClusterDocument> {
  return request<ClusterDocument>(
    `/api/v1/tenants/${tenantId}/clusters/${encodeURIComponent(clusterId)}/notes`,
    { method: "POST", body: JSON.stringify({ note }) },
  );
}

export async function listMyDeadLetters(
  tenantId: string,
  params?: { skip?: number; limit?: number; since_hours?: number },
): Promise<DeadLetterPage> {
  const query = new URLSearchParams();
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.since_hours != null)
    query.set("since_hours", String(params.since_hours));
  const qs = query.toString();
  return request<DeadLetterPage>(
    `/api/v1/tenants/${tenantId}/dead-letters${qs ? `?${qs}` : ""}`,
  );
}

export async function getMyDeadLetter(
  tenantId: string,
  deadLetterId: string,
): Promise<DeadLetterRecord> {
  return request<DeadLetterRecord>(
    `/api/v1/tenants/${tenantId}/dead-letters/${deadLetterId}`,
  );
}

// --- Platform debug traces ---

export async function listDebugTraces(params?: {
  tenant_id?: string;
  alert_id?: string;
  stage?: string;
  outcome?: string;
  release_version?: string;
  release_sha?: string;
  since_hours?: number;
  skip?: number;
  limit?: number;
}): Promise<ProcessingTracePage> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const qs = query.toString();
  return request<ProcessingTracePage>(
    `/api/v1/admin/debug/traces${qs ? `?${qs}` : ""}`,
  );
}

export async function getDebugTrace(
  alertId: string,
): Promise<ProcessingTraceDetail> {
  return request<ProcessingTraceDetail>(
    `/api/v1/admin/debug/traces/${encodeURIComponent(alertId)}`,
  );
}

export async function getPlatformHealth(): Promise<PlatformHealth> {
  return request<PlatformHealth>("/api/v1/health");
}

export { ApiError };

// --- Platform-wide (all tenants) listings ---
//
// These back the "All tenants" scope in the sidebar picker. The server decides
// which tenants are visible from the caller's token, resolves tenant_name, and
// applies `q` across every tenant — the client never fans out or filters.

function platformQuery(params?: {
  q?: string;
  skip?: number;
  limit?: number;
  since_hours?: number;
  status?: string;
  is_active?: boolean;
}): string {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.skip != null) query.set("skip", String(params.skip));
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.since_hours != null) {
    query.set("since_hours", String(params.since_hours));
  }
  if (params?.status) query.set("status", params.status);
  if (params?.is_active !== undefined) {
    query.set("is_active", String(params.is_active));
  }
  const qs = query.toString();
  return qs ? `?${qs}` : "";
}

export async function listAllAlerts(params?: {
  q?: string;
  skip?: number;
  limit?: number;
  since_hours?: number;
}): Promise<PlatformPage<PlatformAlert>> {
  return request<PlatformPage<PlatformAlert>>(
    `/api/v1/admin/alerts${platformQuery(params)}`,
  );
}

export async function getPlatformAlertStats(params?: {
  q?: string;
  since_hours?: number;
}): Promise<AlertStats> {
  return request<AlertStats>(
    `/api/v1/admin/alerts/stats${platformQuery(params)}`,
  );
}

export async function listAllClusters(params?: {
  q?: string;
  skip?: number;
  limit?: number;
  status?: string;
}): Promise<PlatformPage<PlatformCluster>> {
  return request<PlatformPage<PlatformCluster>>(
    `/api/v1/admin/clusters${platformQuery(params)}`,
  );
}

export async function listAllAlertTypeSchemas(params?: {
  q?: string;
  skip?: number;
  limit?: number;
  is_active?: boolean;
}): Promise<PlatformPage<PlatformSchema>> {
  return request<PlatformPage<PlatformSchema>>(
    `/api/v1/admin/alert-type-schemas${platformQuery(params)}`,
  );
}

export async function listAllPlaybooks(params?: {
  q?: string;
  skip?: number;
  limit?: number;
  is_active?: boolean;
}): Promise<PlatformPage<PlatformPlaybook>> {
  return request<PlatformPage<PlatformPlaybook>>(
    `/api/v1/admin/playbooks${platformQuery(params)}`,
  );
}

export async function getPlatformPlaybookStats(): Promise<PlaybookStats> {
  return request<PlaybookStats>("/api/v1/admin/playbooks/stats");
}
