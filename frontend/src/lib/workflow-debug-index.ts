export interface WorkflowExecutionSummary {
  run_id: string;
  alert_id?: string;
  tenant_id: string;
  tenant_name: string;
  alert_type?: string;
  definition_ref?: string;
  definition_code?: string;
  revision?: number;
  state: string;
  created_at?: string;
  release_version?: string;
  release_sha?: string;
}
export interface WorkflowExecutionPage {
  items: WorkflowExecutionSummary[];
  total: number;
  skip: number;
  limit: number;
}
