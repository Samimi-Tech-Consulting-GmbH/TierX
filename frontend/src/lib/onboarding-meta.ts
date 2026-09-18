/** Keys stored in tenant DB `onboarding_status` document (ordered display). */
export const ONBOARDING_KEYS_ORDER = [
  "base_schema_configured",
  "alert_type_registered",
  "fp_rule_defined",
  "kb_document_uploaded",
  "import_completed",
  "live_alert_received",
] as const;

export const ONBOARDING_LABELS: Record<string, string> = {
  base_schema_configured: "Base schema configured",
  alert_type_registered: "Alert type registered",
  fp_rule_defined: "False-positive rule defined",
  kb_document_uploaded: "Knowledge base document uploaded",
  import_completed: "Historical import completed",
  live_alert_received: "Live alert received",
};

/** Short guidance when an item is incomplete (tenant “Getting Started”). */
export const ONBOARDING_GUIDE_HINTS: Record<string, string> = {
  base_schema_configured:
    "Core collections and indexes are provisioned when the tenant is created.",
  alert_type_registered:
    "Register at least one alert type so incoming events can be classified.",
  fp_rule_defined:
    "Define a false-positive rule to tune noise reduction for your environment.",
  kb_document_uploaded:
    "Upload a KB document so enrichment and playbook actions can reference context.",
  import_completed:
    "Finish importing historical alerts so baselines and analytics are meaningful.",
  live_alert_received:
    "Send a test or production alert through ingestion to validate end-to-end flow.",
};

export function parseOnboardingRows(doc: Record<string, unknown>) {
  return ONBOARDING_KEYS_ORDER.map((key) => {
    const done = Boolean(doc[key]);
    const atKey = `${key}_at`;
    const ts =
      atKey in doc && doc[atKey] != null ? String(doc[atKey]) : null;
    return { key, label: ONBOARDING_LABELS[key] ?? key, done, timestamp: ts };
  });
}
