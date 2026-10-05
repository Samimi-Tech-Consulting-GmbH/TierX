export enum TenantStatus {
  ONBOARDING = "ONBOARDING",
  ACTIVE = "ACTIVE",
  SUSPENDED = "SUSPENDED",
  DELETED = "DELETED",
}

export interface TenantCreate {
  name: string;
  display_name: string;
  contact_email?: string;
  allowed_source_systems: string[];
}

export interface TenantUpdate {
  display_name?: string;
  contact_email?: string;
  allowed_source_systems?: string[];
  settings?: Record<string, unknown>;
}

export interface TenantStatusUpdate {
  status: TenantStatus;
}

export interface TenantDocument {
  _id?: string;
  tenant_id: string;
  name: string;
  display_name: string;
  db_name: string;
  status: TenantStatus;
  allowed_source_systems: string[];
  contact_email?: string;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  created_by?: string;
}

export interface TenantPage {
  items: TenantDocument[];
  total: number;
  skip: number;
  limit: number;
}

export type KnowledgeBaseDocumentStatus =
  "PENDING" | "PROCESSING" | "INDEXED" | "FAILED";

export interface KnowledgeBaseDocument {
  document_id: string;
  tenant_id: string;
  original_filename: string;
  file_format: "md" | "txt" | "pdf" | "docx" | "xlsx";
  content_type: string;
  size_bytes: number;
  sha256: string;
  status: KnowledgeBaseDocumentStatus;
  processing_supported: boolean;
  document_version: number;
  parser_version?: string | null;
  index_version?: string | null;
  active_index_generation?: string | null;
  chunk_count: number;
  processing_started_at?: string | null;
  processing_completed_at?: string | null;
  processing_error?: { code?: string; detail?: string } | null;
  semantic_index?: { status: string; model?: string; error?: string; subchunk_count?: number } | null;
  uploaded_by: {
    user_id: string;
    email: string;
  };
  uploaded_at: string;
  updated_at: string;
}

export interface KnowledgeBaseDocumentPage {
  items: KnowledgeBaseDocument[];
  total: number;
  skip: number;
  limit: number;
}

export interface KnowledgeBaseChunk {
  chunk_id: string;
  document_id: string;
  document_version: number;
  chunk_index: number;
  source_start_line: number;
  source_end_line: number;
  heading_path: string[];
  text: string;
  text_sha256: string;
  parser_version: string;
  index_version: string;
}

export interface KnowledgeBaseSearchMatch extends KnowledgeBaseChunk {
  filename: string;
  score: number;
  matched_by: Array<Record<string, unknown>>;
  retrieval_channels?: string[];
  deterministic_score?: number | null;
  semantic_score?: number | null;
  fusion_score?: number | null;
  model?: string | null;
  model_digest?: string | null;
}

export interface KnowledgeBaseSearchResponse {
  query_sha256: string;
  retrieval_version: string;
  status: "OK" | "KB_NOT_AVAILABLE" | "NO_MATCH";
  items: KnowledgeBaseSearchMatch[];
  retrieval_mode?: string;
  semantic_status?: string;
  degraded?: boolean;
}

export interface KnowledgeBaseContext {
  status: "OK" | "SKIPPED" | "KB_NOT_AVAILABLE" | "NO_MATCH" | "ERROR";
  retrieval_version?: string;
  retrieval_mode?: string;
  semantic_status?: string;
  degraded?: boolean;
  query_sha256?: string | null;
  query_summary?: Record<string, unknown>;
  matches?: KnowledgeBaseSearchMatch[];
  reason?: string;
  error?: { code?: string; detail?: string };
}

export interface DashboardCoverage {
  eligible_tenants: number;
  successful_tenants: number;
  failed_tenants: number;
  partial: boolean;
  failed_sources: string[];
  failure_details: Array<{ source: string; error_type: string }>;
}

export interface DashboardKpis {
  critical_alerts: number;
  open_alerts: number;
  active_clusters: number;
  resolved_incidents: number;
  total_alerts: number;
  escalated_alerts: number;
  resolved_clusters: number;
}

export interface DashboardActivityBucket {
  start_at: string;
  end_at: string;
  alerts: number;
  dead_letters: number;
}

export interface PlatformDashboardSummary {
  generated_at: string;
  cache_expires_at: string;
  coverage: DashboardCoverage;
  kpis: DashboardKpis;
  activity: {
    daily: DashboardActivityBucket[];
    weekly: DashboardActivityBucket[];
    monthly: DashboardActivityBucket[];
  };
  recent_activity: Array<{
    kind: "CRITICAL_ALERT" | "CLUSTER";
    tenant_id: string;
    occurred_at: string;
    alert_id?: string | null;
    cluster_id?: string | null;
  }>;
}

export interface TenantDashboardSummary {
  generated_at: string;
  cache_expires_at: string;
  kpis: DashboardKpis;
  activity: PlatformDashboardSummary["activity"];
  recent_activity: PlatformDashboardSummary["recent_activity"];
}

export const ALLOWED_TENANT_SOURCE_SYSTEMS = [
  "SPLUNK",
  "JIRA",
  "CORTEX_XDR",
] as const;

export interface PipelineHealthSummary {
  total_alerts: number;
  alerts_last_24h: number;
  escalated_count: number;
  error_count: number;
  dead_letter_count: number;
  dead_letters_last_24h: number;
}

export interface TenantSelfServiceSettingsPayload {
  similarity_threshold?: number;
  worker_concurrency?: number;
  default_model?: string;
  contact_email?: string;
}

export interface DeadLetterRecord {
  id: string;
  alert_id?: string | null;
  tenant_id?: string | null;
  source_system?: string | null;
  alert_type?: string | null;
  status?: string | null;
  kafka_state?: string | null;
  error_type?: string | null;
  error_detail?: string | null;
  failed_stage?: string | null;
  failed_fields?: unknown[];
  raw_payload?: unknown;
  received_at?: string | null;
  dead_lettered_at?: string | null;
  source_alert?: string | null;
  fingerprint?: string | null;
  analysis_run_id?: string | null;
  analysis_scope_type?: string | null;
  analysis_scope_id?: string | null;
  requested_analysis_version?: number | null;
  retry_cycle?: number | null;
}

export interface DeadLetterPage {
  items: DeadLetterRecord[];
  total: number;
}

// --- Users ---

export enum UserRole {
  PLATFORM_ADMIN = "PLATFORM_ADMIN",
  TENANT_ADMIN = "TENANT_ADMIN",
  TENANT_OPERATOR = "TENANT_OPERATOR",
}

export interface UserDocument {
  _id?: string;
  user_id: string;
  email: string;
  role: UserRole;
  tenant_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  created_by?: string;
}

export interface UserCreatePayload {
  email: string;
  password: string;
  role: UserRole;
  tenant_id?: string;
}

export interface TenantUserCreatePayload {
  email: string;
  password: string;
  role: UserRole;
}

export type PlaybookAdapterEnum =
  | "SPLUNK_SPL"
  | "CORTEX_XDR_QUERY"
  | "GENERIC_HTTP"
  | "NEO4J_CYPHER"
  | "QRADAR_AQL"
  | "WAZUH_API"
  | "MISP_LOOKUP"
  | "KB_VECTOR_SEARCH";

export interface PlaybookAction {
  name: string;
  adapter: PlaybookAdapterEnum;
  query_template: string;
  query_input_fields: string[];
  time: string;
  result: string;
}

export interface PlaybookContextWebhook {
  enabled: boolean;
  url: string;
  timeout_seconds: number;
}

export interface PlaybookContextWebhookProvider extends PlaybookContextWebhook {
  webhook_id: string;
  name: string;
}

export interface PlaybookListItem {
  playbook_id: string;
  version: number;
  tenant_id: string;
  playbook_name: string;
  alert_types: string[];
  is_active: boolean;
  is_system: boolean;
  context_webhook?: PlaybookContextWebhook | null;
  context_webhooks?: PlaybookContextWebhookProvider[] | null;
  enrichment_actions?: string[];
  knowledge_base?: { enabled: boolean; top_k: number; retrieval_mode?: "deterministic" | "hybrid" };
  created_at: string;
  updated_at: string;
}

export interface PlaybookStats {
  total_playbooks: number;
  active_playbooks: number;
  system_playbooks: number;
  covered_alert_types: number;
}

export interface PlaybookDocument {
  playbook_id: string;
  version: number;
  tenant_id: string;
  playbook_name: string;
  actions: PlaybookAction[];
  prompt: string;
  description: string;
  alert_types: string[];
  is_active: boolean;
  is_system: boolean;
  context_webhook?: PlaybookContextWebhook | null;
  context_webhooks?: PlaybookContextWebhookProvider[] | null;
  enrichment_actions?: string[];
  knowledge_base?: { enabled: boolean; top_k: number; retrieval_mode?: "deterministic" | "hybrid" };
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface PlaybookVersionSummary {
  playbook_id: string;
  version: number;
  playbook_name: string;
  alert_types: string[];
  is_active: boolean;
  is_system: boolean;
  context_webhook?: PlaybookContextWebhook | null;
  context_webhooks?: PlaybookContextWebhookProvider[] | null;
  enrichment_actions?: string[];
  knowledge_base?: { enabled: boolean; top_k: number; retrieval_mode?: "deterministic" | "hybrid" };
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface PlaybookReplace {
  playbook_name: string;
  prompt: string;
  description: string;
  alert_types: string[];
  is_active: boolean;
  is_system: boolean;
  actions: PlaybookAction[];
  context_webhook?: PlaybookContextWebhook | null;
  context_webhooks?: PlaybookContextWebhookProvider[] | null;
  enrichment_actions?: string[];
  knowledge_base?: { enabled: boolean; top_k: number; retrieval_mode?: "deterministic" | "hybrid" };
}

export type EnrichmentActionTenantScope = "ALL_TENANTS" | "SELECTED_TENANTS";

export interface EnrichmentActionWrite {
  action_code: string;
  name: string;
  description: string;
  url: string;
  timeout_seconds: number;
  enabled: boolean;
  tenant_scope: EnrichmentActionTenantScope;
  tenant_ids: string[];
}

export interface EnrichmentAction extends EnrichmentActionWrite {
  key_id: string;
  configuration_checksum: string;
  created_at: string;
  updated_at: string;
  created_by: string;
  updated_by: string;
  deleted_at?: string | null;
  last_used_at?: string | null;
  last_status?: string | null;
  last_duration_ms?: number | null;
  last_error_type?: string | null;
}

export interface EnrichmentActionCreated extends EnrichmentAction {
  secret: string;
}

export interface EnrichmentActionPage {
  items: EnrichmentAction[];
  total: number;
  skip: number;
  limit: number;
}

export interface WebhookSecretMetadata {
  configured: boolean;
  scope: "TENANT" | "PLAYBOOK" | "NONE";
  key_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  tenant_fallback_configured: boolean;
  effective_scope: "TENANT" | "PLAYBOOK" | "NONE";
}

export interface WebhookSecretCreated extends WebhookSecretMetadata {
  secret: string;
}

export interface AlertTypeSchemaDocument {
  _id?: string;
  schema_id: string;
  tenant_id: string;
  alert_type: string;
  version: string;
  description?: string | null;
  fields: Record<string, unknown>[];
  critical_fields: string[];
  field_mapping: Record<string, string>;
  playbook_id?: string | null;
  is_active: boolean;
  severity?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface AlertTypeSchemaListResponse {
  items: AlertTypeSchemaDocument[];
  total: number;
  skip: number;
  limit: number;
}

// --- Alerts ---

export type AlertSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";

export interface AlertDocument {
  id: string;
  alert_id: string;
  tenant_id: string;
  alert_type: string;
  source_system: string;
  raw_payload?: unknown;
  source_reference?: Record<string, unknown> | null;
  normalized_payload?: Record<string, unknown> | null;
  severity: AlertSeverity;
  status?: string | null;
  kafka_state?: string | null;
  fingerprint?: string | null;
  validated?: boolean | null;
  normalized?: boolean | null;
  enriched?: boolean | null;
  playbook_id?: string | null;
  playbook_version?: number | null;
  playbook_resolution?: string | null;
  prompt_webhook_context?: PromptWebhookContext | null;
  prompt_webhook_contexts?: PromptWebhookContext[] | null;
  enrichment_action_batch_id?: string | null;
  enrichment_action_status?: string | null;
  enrichment_action_results?: EnrichmentActionResult[] | null;
  enrichment?: {
    kb_context?: KnowledgeBaseContext | null;
    [key: string]: unknown;
  } | null;
  cluster_id?: string | null;
  clustering_status?: string | null;
  debounce_outcome?: string | null;
  analysis_type?: string | null;
  correlation_result?: Record<string, unknown> | null;
  analysis_status?: string | null;
  analysis_error?: Record<string, unknown> | null;
  requested_analysis_version?: number | null;
  analyzed_version?: number | null;
  last_analysis_requested_at?: string | null;
  last_analyzed_at?: string | null;
  alert_analysis?: AnalysisResult | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PromptWebhookContext {
  status: "SUCCEEDED" | "FAILED" | "SKIPPED";
  webhook_id?: string;
  webhook_name?: string;
  config_order?: number;
  delivery_id?: string;
  playbook_id?: string;
  playbook_version?: number;
  effective_credential_scope?: "TENANT" | "PLAYBOOK";
  key_id?: string;
  duration_ms?: number;
  response_sha256?: string;
  response_size_bytes?: number;
  prompt_footer?: string;
  error_type?: string;
  completed_at?: string;
}

export interface EnrichmentActionResult {
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED";
  action_code: string;
  config_order: number;
  delivery_id: string;
  playbook_id: string;
  playbook_version: number;
  configuration_checksum?: string;
  key_id?: string;
  outcome?: string;
  duration_ms?: number;
  deadline_at?: string;
  last_heartbeat_at?: string;
  response_sha256?: string;
  response_size_bytes?: number;
  context_text?: string;
  error_type?: string;
  completed_at?: string;
}

export interface AlertPage {
  items: AlertDocument[];
  total: number;
}

export interface AlertStats {
  filtered_total: number;
  severity: Record<AlertSeverity, number>;
}

// --- LLM analysis and clusters ---

export interface PromptSource {
  type: "PLAYBOOK" | "SYSTEM" | "PLAYBOOK_WEBHOOK" | "ENRICHMENT_ACTION";
  playbook_id?: string;
  template_id?: string;
  version?: number;
  action_code?: string;
  configuration_checksum?: string;
  outcomes?: string[];
  alert_types?: string[];
  alert_ids?: string[];
  webhook_ids?: string[];
  webhook_names?: string[];
  config_orders?: number[];
  response_sha256?: string;
  response_size_bytes?: number;
  omitted?: boolean;
  omission_reason?: string | null;
}

export interface AnalysisResult {
  version: number;
  headline: string;
  narrative: string;
  kill_chain: string[];
  confidence: "HIGH" | "MEDIUM" | "LOW";
  recommended_actions: string[];
  generated_at: string;
  model: string;
  model_digest?: string;
  is_final: boolean;
  trigger_reason: string;
  prompt_source: "PLAYBOOK" | "SYSTEM" | "COMPOSITE";
  prompt_sources: PromptSource[];
  superseded_by_cluster_id?: string;
  superseded_at?: string;
  history?: AnalysisResult[];
}

export interface AnalysisRun {
  analysis_run_id: string;
  tenant_id: string;
  analysis_scope_type: "ALERT" | "CLUSTER";
  analysis_scope_id: string;
  requested_analysis_version: number;
  state: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "SUPERSEDED";
  retry_cycle: number;
  attempts_total: number;
  attempts_in_cycle: number;
  model?: string | null;
  model_digest?: string | null;
  prompt_source?: string | null;
  prompt_sources: PromptSource[];
  last_error?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface AnalysisRunPage {
  items: AnalysisRun[];
  total: number;
}

export interface AnalysisRetryResponse {
  analysis_run_id: string;
  analysis_scope_type: "ALERT" | "CLUSTER";
  analysis_scope_id: string;
  requested_analysis_version: number;
  retry_cycle: number;
  state: "PENDING";
}

export interface ClusterDocument {
  cluster_id: string;
  tenant_id: string;
  lead_alert_id: string;
  alert_ids: string[];
  alert_count: number;
  affected_host_count?: number | null;
  is_open_for_grouping: boolean;
  debounce_expires_at: string;
  grouping_window_expires_at: string;
  correlation_basis: Record<string, unknown>;
  first_seen: string;
  last_seen: string;
  severity: Record<string, unknown>;
  debounce_outcome?: string | null;
  clustering_status?: string | null;
  analysis_type: string;
  analyzed_version: number;
  analyzed_alert_count: number;
  requested_analysis_version: number;
  last_analyzed_at?: string | null;
  summary?: AnalysisResult | null;
  analysis_status?: string | null;
  analysis_error?: Record<string, unknown> | null;
  status: string;
  assigned_to?: string | null;
  verdict?: string | null;
  analyst_notes: Record<string, unknown>[];
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
}

export interface ClusterListItem {
  cluster_id: string;
  status: string;
  clustering_status?: string | null;
  alert_count: number;
  severity: Record<string, unknown>;
  first_seen: string;
  last_seen: string;
  assigned_to?: string | null;
  is_open_for_grouping: boolean;
  summary?: AnalysisResult | null;
  analysis_status?: string | null;
  analyzed_version: number;
  requested_analysis_version: number;
  last_analyzed_at?: string | null;
  created_at: string;
}

export interface ClusterPage {
  items: ClusterListItem[];
  total: number;
}

// --- Jira site connections and project routes ---

export type JiraIntegrationState = "ACTIVE" | "REVOKED";

export interface JiraSiteConnection {
  integration_id: string;
  name: string;
  jira_cloud_id: string;
  jira_site_url?: string | null;
  state: JiraIntegrationState;
  secret_prefix: string;
  route_count: number;
  created_at: string;
  updated_at: string;
  created_by: string;
  last_used_at?: string | null;
  last_submission_at?: string | null;
  legacy_tenant_id?: string | null;
}

export interface JiraSiteConnectionCreated extends JiraSiteConnection {
  secret: string;
}

export interface JiraProjectRoute {
  route_id: string;
  integration_id: string;
  project_key: string;
  tenant_id: string;
  tenant_name: string;
  source_system: string;
  alert_type: string;
  enabled: boolean;
  revision: number;
  effective_schema_id?: string | null;
  effective_schema_version?: string | null;
  event_timestamp_path?: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
  updated_by: string;
  last_used_at?: string | null;
  last_error?: Record<string, unknown> | null;
}

export interface JiraSiteConnectionCreate {
  name: string;
  jira_cloud_id: string;
  jira_site_url: string;
}

export interface JiraProjectRouteWrite {
  project_key: string;
  tenant_id: string;
  source_system: string;
  alert_type: string;
  enabled: boolean;
}

// --- Processing debug traces ---

export type TraceOutcome = "RUNNING" | "SUCCEEDED" | "FAILED";
export type TraceTerminalState = TraceOutcome | "STALLED";

export interface TraceSnapshot {
  value: unknown;
  truncated: boolean;
  size_bytes: number;
  sha256?: string;
}

export interface ProcessingTraceSpan {
  span_id: string;
  alert_id: string;
  tenant_id?: string | null;
  alert_type?: string | null;
  source_system?: string | null;
  stage: string;
  sequence: number;
  service: string;
  release_sha?: string | null;
  release_version?: string | null;
  submitted_by?: string | null;
  outcome: TraceOutcome;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  input_snapshot?: TraceSnapshot | null;
  output_snapshot?: TraceSnapshot | null;
  checks?: Record<string, unknown>[];
  decisions?: Record<string, unknown>;
  error?: Record<string, unknown> | null;
}

export interface ProcessingTraceSummary {
  alert_id: string;
  tenant_id?: string | null;
  alert_type?: string | null;
  source_system?: string | null;
  current_stage?: string | null;
  current_outcome?: TraceOutcome | null;
  terminal_state: TraceTerminalState;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  processing_duration_ms?: number | null;
  span_count: number;
  release_sha?: string | null;
  release_version?: string | null;
  release_versions: string[];
  release_shas: string[];
  mixed_releases: boolean;
}

export interface ProcessingTracePage {
  items: ProcessingTraceSummary[];
  total: number;
  skip: number;
  limit: number;
}

export interface ProcessingTraceDetail {
  summary: ProcessingTraceSummary;
  spans: ProcessingTraceSpan[];
  pipeline_boundary: string;
}

export const VALID_TRANSITIONS: Record<TenantStatus, TenantStatus[]> = {
  [TenantStatus.ONBOARDING]: [TenantStatus.ACTIVE, TenantStatus.DELETED],
  [TenantStatus.ACTIVE]: [TenantStatus.SUSPENDED, TenantStatus.DELETED],
  [TenantStatus.SUSPENDED]: [TenantStatus.ACTIVE, TenantStatus.DELETED],
  [TenantStatus.DELETED]: [],
};

export interface PlatformHealth {
  status: "HEALTHY" | "UNHEALTHY";
  components: Record<string, string>;
  llm_analysis_enabled: boolean;
  release_version: string;
  release_sha: string;
}

export interface LatestRelease {
  enabled: boolean;
  status: "AVAILABLE" | "UNAVAILABLE" | "DISABLED";
  latest_version: string | null;
  release_url: string | null;
  checked_at: string | null;
}

export interface TenantOwned {
  tenant_id?: string | null;
  tenant_name?: string | null;
}

export type PlatformAlert = AlertDocument & TenantOwned;
export type PlatformCluster = ClusterListItem & TenantOwned;
export type PlatformSchema = AlertTypeSchemaDocument & TenantOwned;
export type PlatformPlaybook = PlaybookListItem & TenantOwned;

export interface PlatformPage<T> {
  items: T[];
  total: number;
  skip: number;
  limit: number;
}
