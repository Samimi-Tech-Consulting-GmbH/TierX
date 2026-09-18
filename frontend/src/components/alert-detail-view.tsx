"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Braces,
  Copy,
  ExternalLink,
  FileText,
  ScanSearch,
} from "lucide-react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api";
import type { AlertDocument } from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import { formatDurationMs } from "@/lib/duration";
import { alertTypeLabel, severityOf, statusTone } from "@/lib/alert-display";
import { PANEL, PANEL_NOTE, PANEL_TITLE, PILL } from "@/lib/cluster-display";
import { scopedApi, scopedRoutes, type TenantScope } from "@/lib/tenant-scope";
import { Button } from "@/components/ui/button";
import { AlertAnalysisPanel } from "@/components/alert-analysis-panel";
import { cn } from "@/lib/utils";

function Field({
  label,
  value,
  tone,
  mono,
}: {
  label: string;
  value: string;
  tone?: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-lg bg-[#404040] px-4 py-3">
      <div className="text-xs text-[#a3a3a3]">{label}</div>
      {tone ? (
        <span className={cn(PILL, tone, "mt-1")}>{value || "—"}</span>
      ) : (
        <div
          className={cn(
            "mt-1 truncate text-sm font-bold text-foreground",
            mono && "font-mono text-xs font-normal",
          )}
          title={value}
        >
          {value || "—"}
        </div>
      )}
    </div>
  );
}

export function AlertDetailView({
  tenantId,
  alertId,
  scope,
}: {
  tenantId: string;
  alertId: string;
  scope: TenantScope;
}) {
  const isAdmin = scope === "admin";

  const [alert, setAlert] = useState<AlertDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    scopedApi(scope)
      .getAlert(tenantId, alertId)
      .then((a) => {
        if (!cancelled) setAlert(a);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setError("Alert not found.");
        } else {
          setError("Failed to load alert.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, alertId, scope]);

  const listHref = scopedRoutes(scope, tenantId).alerts;

  function copyJson(payload: unknown) {
    navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
    toast.info("Copied to clipboard");
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (error || !alert) {
    return (
      <div className="space-y-6">
        <Button
          variant="ghost"
          size="icon"
          nativeButton={false}
          render={<Link href={listHref} />}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <p className="text-sm text-destructive">{error ?? "Not found"}</p>
        <Button
          variant="outline"
          nativeButton={false}
          render={<Link href={listHref} />}
        >
          Back to list
        </Button>
      </div>
    );
  }

  const normalizedPretty =
    alert.normalized_payload != null
      ? JSON.stringify(alert.normalized_payload, null, 2)
      : null;

  const rawPretty =
    alert.raw_payload != null
      ? JSON.stringify(alert.raw_payload, null, 2)
      : null;

  const sourceReference = alert.source_reference;
  const jiraIssueUrl =
    sourceReference?.type === "JIRA" &&
    typeof sourceReference.issue_url === "string" &&
    sourceReference.issue_url.startsWith("https://")
      ? sourceReference.issue_url
      : null;

  const webhookContexts =
    alert.prompt_webhook_contexts ??
    (alert.prompt_webhook_context
      ? [
          {
            ...alert.prompt_webhook_context,
            webhook_id: "legacy-context",
            webhook_name: "Legacy context webhook",
            config_order: 0,
          },
        ]
      : []);
  const enrichmentActionResults = alert.enrichment_action_results ?? [];
  const knowledgeBaseContext = alert.enrichment?.kb_context;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start gap-4">
        <Button
          variant="ghost"
          size="icon"
          nativeButton={false}
          render={<Link href={listHref} />}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0 flex-1 space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">Alert detail</h1>
          <p className="break-all font-mono text-xs text-muted-foreground">
            {alert.alert_id}
          </p>
        </div>
        {/* Processing traces live under the platform-admin debug tree. */}
        {isAdmin ? (
          <Link
            href={`/dashboard/admin/debug/alerts/${encodeURIComponent(alert.alert_id)}`}
            className="inline-flex h-10 shrink-0 items-center gap-2 rounded-md bg-[#404040] px-5 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
          >
            <ScanSearch className="size-4" />
            Processing trace
          </Link>
        ) : null}
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <FileText className="size-4 text-primary" />
          Metadata
        </h3>
        <p className={PANEL_NOTE}>Core alert fields.</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Alert type" value={alertTypeLabel(alert.alert_type)} />
          <Field label="Source system" value={alert.source_system} />
          <Field
            label="Status"
            value={alert.status ?? "—"}
            tone={statusTone(alert.status)}
          />
          <Field label="Severity" value={severityOf(alert).label} />
          <Field label="Kafka state" value={alert.kafka_state ?? "—"} />
          <Field label="Playbook" value={alert.playbook_id ?? "—"} />
          <Field
            label="Playbook resolution"
            value={alert.playbook_resolution ?? "—"}
          />
          <Field
            label="Pipeline"
            value={[
              alert.validated ? "Validated" : null,
              alert.normalized ? "Normalized" : null,
              alert.enriched ? "Enriched" : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          />
          <Field label="Fingerprint" value={alert.fingerprint ?? "—"} mono />
          <Field
            label="Created"
            value={formatLocaleDateTime(alert.created_at)}
          />
          <Field
            label="Updated"
            value={formatLocaleDateTime(alert.updated_at)}
          />
        </div>
      </div>

      {sourceReference?.type === "JIRA" ? (
        <div className={PANEL}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className={PANEL_TITLE}>
                <ExternalLink className="size-4 text-primary" />
                Jira provenance
              </h3>
              <p className={PANEL_NOTE}>
                Transport identity recorded separately from the raw source
                alert.
              </p>
            </div>
            {jiraIssueUrl ? (
              <a
                href={jiraIssueUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-[#404040] px-4 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
              >
                Open Jira issue
                <ExternalLink className="size-3.5" />
              </a>
            ) : null}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field
              label="Project / issue"
              value={`${String(sourceReference.project_key ?? "—")} / ${String(sourceReference.issue_key ?? "—")}`}
            />
            <Field
              label="Content source"
              value={String(
                (
                  sourceReference.content_source as
                    Record<string, unknown> | undefined
                )?.kind ?? "—",
              )}
            />
            <Field
              label="Content SHA-256"
              value={String(sourceReference.content_sha256 ?? "—")}
              mono
            />
          </div>
        </div>
      ) : null}

      {webhookContexts.length > 0 ? (
        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>
            <Braces className="size-4 text-primary" />
            Playbook context providers
          </h3>
          <p className={PANEL_NOTE}>
            Independent provider outcomes recorded during enrichment in
            configured order. Signing credentials and headers are never shown
            here.
          </p>
          <div className="mt-4 space-y-4">
            {webhookContexts.map((context, index) => (
              <div
                key={context.delivery_id ?? `${context.webhook_id}-${index}`}
                className="rounded-lg border border-white/5 bg-[#303030] p-4"
              >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-bold text-foreground">
                      {context.webhook_name ??
                        context.webhook_id ??
                        `Provider ${index + 1}`}
                    </p>
                    <p className="font-mono text-xs text-muted-foreground">
                      {context.webhook_id ?? "legacy-context"} · order{" "}
                      {(context.config_order ?? index) + 1}
                    </p>
                  </div>
                  <span className="text-sm font-bold text-foreground">
                    {context.status}
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <Field
                    label="Credential scope"
                    value={context.effective_credential_scope ?? "—"}
                  />
                  <Field
                    label="Duration"
                    value={
                      context.duration_ms == null
                        ? "—"
                        : formatDurationMs(context.duration_ms)
                    }
                  />
                  <Field
                    label="Delivery ID"
                    value={context.delivery_id ?? "—"}
                    mono
                  />
                  <Field
                    label="Response checksum"
                    value={context.response_sha256 ?? "—"}
                    mono
                  />
                  <Field label="Failure" value={context.error_type ?? "—"} />
                  <Field
                    label="Completed"
                    value={formatLocaleDateTime(context.completed_at)}
                  />
                </div>
                {context.prompt_footer ? (
                  <pre className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-[#171717] p-4 text-sm text-[#d4d4d4]">
                    {context.prompt_footer}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {knowledgeBaseContext ? (
        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>
            <Braces className="size-4 text-primary" />
            Knowledge Base evidence
          </h3>
          <p className={PANEL_NOTE}>
            Tenant documents selected during enrichment. This content is
            supplied to analysis as untrusted evidence and cannot directly
            change a verdict.
          </p>
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <Field label="Status" value={knowledgeBaseContext.status} />
            <Field label="Mode" value={knowledgeBaseContext.retrieval_mode ?? "deterministic"} />
            <Field label="Semantic retrieval" value={knowledgeBaseContext.semantic_status ?? "Not requested"} />
            {knowledgeBaseContext.degraded && <p role="status">Semantic retrieval unavailable; deterministic fallback used.</p>}
            <Field
              label="Retrieval version"
              value={knowledgeBaseContext.retrieval_version ?? "—"}
            />
            <Field
              label="Query checksum"
              value={knowledgeBaseContext.query_sha256 ?? "—"}
              mono
            />
          </div>
          <div className="mt-4 space-y-3">
            {(knowledgeBaseContext.matches ?? []).map((match) => (
              <div
                key={match.chunk_id}
                className="rounded-lg border border-white/5 bg-[#303030] p-4"
              >
                <div className="flex flex-wrap justify-between gap-2">
                  <strong>{match.filename}</strong>
                  <span className="text-sm">
                    Deterministic {match.score.toFixed(1)}
                    {match.semantic_score != null ? ` · Semantic ${match.semantic_score.toFixed(3)}` : ""}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {match.heading_path.join(" › ") || "Unsectioned text"} · chunk{" "}
                  {match.chunk_index + 1}
                  {match.retrieval_channels?.length ? ` · ${match.retrieval_channels.join(" + ")}` : ""}
                  {match.model ? ` · ${match.model}` : ""}
                </p>
                <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-[#171717] p-4 text-sm text-[#d4d4d4]">
                  {match.text}
                </pre>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {enrichmentActionResults.length > 0 ? (
        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>
            <Braces className="size-4 text-primary" />
            Platform-managed enrichment actions
          </h3>
          <p className={PANEL_NOTE}>
            Signed external providers received only the normalized alert.
            Returned text is treated as untrusted evidence, never as executable
            instructions.
          </p>
          <div className="mt-4 space-y-4">
            {enrichmentActionResults.map((result) => (
              <div
                key={result.delivery_id}
                className="rounded-lg border border-white/5 bg-[#303030] p-4"
              >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-bold text-foreground">
                      {result.action_code}
                    </p>
                    <p className="font-mono text-xs text-muted-foreground">
                      order {result.config_order + 1} · {result.delivery_id}
                    </p>
                  </div>
                  <span className="text-sm font-bold">{result.status}</span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <Field label="Outcome" value={result.outcome ?? "—"} />
                  <Field
                    label="Duration"
                    value={
                      result.duration_ms == null
                        ? "—"
                        : formatDurationMs(result.duration_ms)
                    }
                  />
                  <Field label="Failure" value={result.error_type ?? "—"} />
                  <Field
                    label="Deadline"
                    value={formatLocaleDateTime(result.deadline_at)}
                  />
                  <Field
                    label="Last heartbeat"
                    value={formatLocaleDateTime(result.last_heartbeat_at)}
                  />
                  <Field
                    label="Configuration"
                    value={result.configuration_checksum ?? "—"}
                    mono
                  />
                </div>
                {result.context_text ? (
                  <pre className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-[#171717] p-4 text-sm text-[#d4d4d4]">
                    {result.context_text}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <AlertAnalysisPanel
        tenantId={tenantId}
        alert={alert}
        adminView={isAdmin}
      />

      <PayloadPanel
        title="Normalized payload"
        note="ECS-mapped fields."
        json={normalizedPretty}
        onCopy={() => copyJson(alert.normalized_payload)}
        emptyLabel="No normalized payload."
      />

      <PayloadPanel
        title="Raw payload"
        note="Original message body from the source system."
        json={rawPretty}
        onCopy={() => copyJson(alert.raw_payload)}
        emptyLabel="No raw payload."
      />
    </div>
  );
}

function PayloadPanel({
  title,
  note,
  json,
  onCopy,
  emptyLabel,
}: {
  title: string;
  note: string;
  json: string | null;
  onCopy: () => void;
  emptyLabel: string;
}) {
  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className={PANEL_TITLE}>
            <Braces className="size-4 text-primary" />
            {title}
          </h3>
          <p className={PANEL_NOTE}>{note}</p>
        </div>
        {json ? (
          <button
            type="button"
            onClick={onCopy}
            className="inline-flex h-9 shrink-0 items-center gap-2 rounded-md bg-[#404040] px-4 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
          >
            <Copy className="size-3.5" />
            Copy JSON
          </button>
        ) : null}
      </div>
      {json ? (
        <pre className="mt-4 max-h-[min(70vh,720px)] overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[#171717] p-4 font-mono text-xs text-[#d4d4d4]">
          {json}
        </pre>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">{emptyLabel}</p>
      )}
    </div>
  );
}
