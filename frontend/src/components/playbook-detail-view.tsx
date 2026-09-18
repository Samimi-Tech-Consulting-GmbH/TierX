"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowDown,
  BookOpen,
  Braces,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  History,
  ListChecks,
  Pencil,
  PlayCircle,
  Sparkles,
  KeyRound,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import {
  deletePlaybook,
  getPlaybook,
  listPlaybookVersions,
  replacePlaybook,
  ApiError,
  getTenantWebhookSecret,
  rotateTenantWebhookSecret,
  deleteTenantWebhookSecret,
  getPlaybookWebhookSecret,
  rotatePlaybookWebhookSecret,
  deletePlaybookWebhookSecret,
} from "@/lib/api";
import type {
  PlaybookDocument,
  PlaybookVersionSummary,
  WebhookSecretMetadata,
} from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  TABLE_HEAD,
  TABLE_ROW,
} from "@/lib/cluster-display";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function PlaybookDetailView({
  tenantId,
  playbookId,
  canWrite,
  onChanged,
}: {
  tenantId: string;
  playbookId: string;
  canWrite: boolean;
  onChanged?: () => void;
}) {
  const [doc, setDoc] = useState<PlaybookDocument | null>(null);
  const [versions, setVersions] = useState<PlaybookVersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusPromptOpen, setStatusPromptOpen] = useState(false);
  const [savingStatus, setSavingStatus] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getPlaybook(tenantId, playbookId)
      .then((d) => {
        if (!cancelled) setDoc(d);
      })
      .catch(() => {
        if (!cancelled) {
          setDoc(null);
          toast.error("Failed to load playbook");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    listPlaybookVersions(tenantId, playbookId)
      .then((v) => {
        if (!cancelled) setVersions(v);
      })
      .catch(() => {
        if (!cancelled) setVersions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, playbookId]);

  async function handleToggleStatus() {
    if (!doc || !canWrite) return;
    setSavingStatus(true);
    try {
      if (doc.is_active) {
        const updated = await deletePlaybook(tenantId, playbookId);
        setDoc(updated);
        toast.success(`"${updated.playbook_name}" is no longer active.`);
      } else {
        const updated = await replacePlaybook(tenantId, playbookId, {
          playbook_name: doc.playbook_name,
          prompt: doc.prompt,
          description: doc.description,
          alert_types: doc.alert_types ?? [],
          is_active: true,
          is_system: doc.is_system,
          actions: doc.actions ?? [],
          context_webhook: doc.context_webhook,
          context_webhooks: doc.context_webhooks,
          enrichment_actions: doc.enrichment_actions ?? [],
          knowledge_base: doc.knowledge_base ?? { enabled: false, top_k: 5 },
        });
        setDoc(updated);
        setVersions(await listPlaybookVersions(tenantId, playbookId));
        toast.success(
          `"${updated.playbook_name}" is active again as v${updated.version}.`,
        );
      }
      setStatusPromptOpen(false);
      onChanged?.();
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.detail : "Status change failed",
      );
    } finally {
      setSavingStatus(false);
    }
  }

  if (loading) {
    return (
      <div className={cn(PANEL, "space-y-3")}>
        {Array.from({ length: 6 }).map((_, index) => (
          <div
            key={index}
            className="h-10 w-full animate-pulse rounded bg-white/5"
          />
        ))}
      </div>
    );
  }

  if (!doc) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Playbook not found</h3>
        <p className={PANEL_NOTE}>
          It may have been removed, or it belongs to another tenant.
        </p>
      </div>
    );
  }

  const alertTypes = doc.alert_types ?? [];
  const actions = doc.actions ?? [];
  const enrichmentActions = doc.enrichment_actions ?? [];
  const knowledgeBase = doc.knowledge_base ?? { enabled: false, top_k: 5 };
  const contextProviders =
    doc.context_webhooks ??
    (doc.context_webhook
      ? [
          {
            ...doc.context_webhook,
            webhook_id: "legacy-context",
            name: "Legacy context webhook",
          },
        ]
      : []);

  return (
    <div className="flex flex-col gap-6">
      <div className={cn(PANEL, "flex flex-col gap-6")}>
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-white/5 pb-4">
          <div>
            <h3 className="text-lg font-bold text-foreground">
              {doc.playbook_name}
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Stored playbook · v{doc.version}
              {doc.is_system ? " · system" : ""}
              <span className="ml-2 font-mono text-xs">{doc.playbook_id}</span>
            </p>
          </div>
          {canWrite ? (
            <Link
              href={`/dashboard/${tenantId}/playbooks/new?updatePlaybook=${doc.playbook_id}`}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-[#404040] px-4 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
            >
              <Pencil className="size-4" />
              Version
            </Link>
          ) : null}
        </div>

        <div>
          <h4 className={PANEL_TITLE}>
            <ListChecks className="size-4 text-primary" />
            Workflow
          </h4>
          <p className={PANEL_NOTE}>
            Routing trigger, stored enrichment actions, then the analysis
            prompt.
          </p>

          <div className="mt-5 flex flex-col items-center gap-0">
            <WorkflowNode
              tone="trigger"
              icon={<PlayCircle className="size-4 text-white" />}
              title="Trigger"
              centered
            >
              <p className="text-xs text-white/80">
                {alertTypes.length > 0
                  ? `Alert types: ${alertTypes.join(", ")}`
                  : "Any alert type (no routing labels)"}
              </p>
              <p className="text-xs text-white/80">
                {doc.is_active
                  ? "Runs on matching alerts"
                  : "Inactive — will not run"}
              </p>
            </WorkflowNode>

            {enrichmentActions.length === 0 ? (
              <>
                <Connector />
                <div className="w-full max-w-[400px] rounded-lg border border-dashed border-white/15 px-4 py-3 text-center text-xs text-muted-foreground">
                  No platform-managed enrichment actions referenced by this
                  playbook.
                </div>
              </>
            ) : (
              enrichmentActions.map((actionCode, index) => (
                <div
                  key={actionCode}
                  className="flex w-full flex-col items-center"
                >
                  <Connector />
                  <WorkflowNode
                    tone="step"
                    icon={<Braces className="size-4 text-primary" />}
                    title={`Enrichment action ${index + 1}: ${actionCode}`}
                  >
                    <p className="text-xs text-muted-foreground">
                      Signed external evidence provider
                    </p>
                  </WorkflowNode>
                </div>
              ))
            )}

            {contextProviders.map((provider) => (
              <div
                key={provider.webhook_id}
                className="flex w-full flex-col items-center"
              >
                <Connector />
                <WorkflowNode
                  tone="step"
                  icon={<Braces className="size-4 text-primary" />}
                  title={`Context provider: ${provider.name}`}
                >
                  <p className="break-all text-xs text-muted-foreground">
                    {provider.url}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {provider.enabled ? "Enabled" : "Disabled"} ·{" "}
                    {provider.timeout_seconds}s timeout
                  </p>
                </WorkflowNode>
              </div>
            ))}

            {knowledgeBase.enabled && (
              <div className="flex w-full flex-col items-center">
                <Connector />
                <WorkflowNode
                  tone="step"
                  icon={<BookOpen className="size-4 text-primary" />}
                  title="Tenant Knowledge Base"
                >
                  <p className="text-xs text-muted-foreground">
                    {knowledgeBase.retrieval_mode ?? "deterministic"} retrieval · Up to {knowledgeBase.top_k} indexed evidence
                    chunks
                  </p>
                </WorkflowNode>
              </div>
            )}

            <Connector />
            <WorkflowNode
              tone="step"
              icon={<Sparkles className="size-4 text-[#fbbf24]" />}
              title="Analysis prompt"
            >
              <p className="line-clamp-3 text-xs text-muted-foreground">
                {doc.prompt || "No prompt stored."}
              </p>
            </WorkflowNode>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/5 pt-4 text-sm text-muted-foreground">
          <span>
            Last modified {formatLocaleDateTime(doc.updated_at)} by{" "}
            {doc.created_by}
          </span>
          <span className="flex items-center gap-3">
            <span>Status:</span>
            <span
              className={cn(
                "font-bold",
                doc.is_active ? "text-[#4ade80]" : "text-muted-foreground",
              )}
            >
              {doc.is_active ? "Active" : "Inactive"}
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={doc.is_active}
              aria-label={
                doc.is_active ? "Deactivate playbook" : "Reactivate playbook"
              }
              disabled={!canWrite || savingStatus}
              onClick={() => setStatusPromptOpen(true)}
              className={cn(
                "relative h-5 w-10 shrink-0 rounded-full transition-colors",
                doc.is_active ? "bg-[#16a34a]" : "bg-[#525252]",
                canWrite && !savingStatus
                  ? "cursor-pointer"
                  : "cursor-not-allowed opacity-60",
              )}
            >
              <span
                className={cn(
                  "absolute top-0.5 size-4 rounded-full bg-white transition-all",
                  doc.is_active ? "left-[22px]" : "left-0.5",
                )}
              />
            </button>
          </span>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className={PANEL}>
          <h4 className={PANEL_TITLE}>
            <BookOpen className="size-4 text-primary" />
            Overview
          </h4>
          <dl className="mt-3 space-y-2 text-sm">
            <DetailRow label="Version" value={`v${doc.version}`} />
            <DetailRow
              label="Alert types"
              value={alertTypes.length > 0 ? alertTypes.join(", ") : "—"}
            />
            <DetailRow label="Active" value={doc.is_active ? "yes" : "no"} />
            <DetailRow
              label="Knowledge Base"
              value={
                knowledgeBase.enabled
                  ? `enabled · ${knowledgeBase.retrieval_mode ?? "deterministic"} · top ${knowledgeBase.top_k}`
                  : "disabled"
              }
            />
            <DetailRow label="System" value={doc.is_system ? "yes" : "no"} />
            <DetailRow label="Created by" value={doc.created_by} />
            <DetailRow
              label="Created"
              value={formatLocaleDateTime(doc.created_at)}
            />
          </dl>
          <p className="mt-4 border-t border-white/5 pt-3 text-sm text-muted-foreground">
            {doc.description || "No description stored."}
          </p>
        </div>

        <PromptCard prompt={doc.prompt} />
      </div>

      <WebhookCredentialPanel
        tenantId={tenantId}
        playbookId={playbookId}
        providers={contextProviders}
        legacy={doc.context_webhooks == null && doc.context_webhook != null}
        canWrite={canWrite}
      />

      <div className={PANEL}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h4 className={PANEL_TITLE}>
              <Braces className="size-4 text-primary" />
              Actions (JSON)
            </h4>
            <p className={PANEL_NOTE}>
              {actions.length} stored action payload
              {actions.length === 1 ? "" : "s"}
            </p>
          </div>
          <CopyButton
            value={JSON.stringify(actions, null, 2)}
            label="action payloads"
          />
        </div>
        <pre className="mt-3 max-h-96 overflow-auto rounded-lg bg-[#171717] p-4 font-mono text-xs text-[#d4d4d4]">
          {JSON.stringify(actions, null, 2)}
        </pre>
      </div>

      <div className={PANEL}>
        <h4 className={PANEL_TITLE}>
          <Braces className="size-4 text-primary" />
          Platform-managed enrichment action codes
        </h4>
        <p className={PANEL_NOTE}>
          These providers return untrusted evidence before correlation and
          analysis.
        </p>
        <pre className="mt-3 rounded-lg bg-[#171717] p-4 font-mono text-xs text-[#d4d4d4]">
          {JSON.stringify(enrichmentActions, null, 2)}
        </pre>
      </div>

      {versions.length > 1 ? (
        <div className={PANEL}>
          <h4 className={PANEL_TITLE}>
            <History className="size-4 text-primary" />
            Version history
          </h4>
          <p className={PANEL_NOTE}>
            Stored revisions of this playbook id, newest first.
          </p>
          <div className="mt-4 overflow-x-auto rounded-lg">
            <table className="w-full min-w-[560px] text-left">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className="w-20 px-4 py-3">Ver.</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Updated</th>
                  <th className="px-4 py-3">Created by</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.version} className={TABLE_ROW}>
                    <td className="px-4 py-3 text-sm font-bold tabular-nums text-foreground">
                      v{v.version}
                    </td>
                    <td className="px-4 py-3 text-sm text-foreground">
                      {v.playbook_name}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-muted-foreground">
                      {formatLocaleDateTime(v.updated_at)}
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">
                      {v.created_by}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <Dialog open={statusPromptOpen} onOpenChange={setStatusPromptOpen}>
        <DialogContent className="sm:max-w-md" showCloseButton>
          <DialogHeader>
            <DialogTitle>
              {doc.is_active ? "Deactivate playbook?" : "Reactivate playbook?"}
            </DialogTitle>
            <DialogDescription className="text-pretty">
              {doc.is_active ? (
                <>
                  &quot;{doc.playbook_name}&quot; stops matching new alerts.
                  Every stored version is marked inactive; the content stays
                  available.
                </>
              ) : (
                <>
                  There is no reactivate endpoint, so this re-saves the current
                  content as version {doc.version + 1} with{" "}
                  <code className="rounded bg-[#404040] px-1 text-xs">
                    is_active: true
                  </code>
                  . Version {doc.version} stays in the history.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setStatusPromptOpen(false)}
              disabled={savingStatus}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={doc.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={savingStatus}
            >
              {savingStatus
                ? "Saving…"
                : doc.is_active
                  ? "Deactivate"
                  : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function WebhookCredentialPanel({
  tenantId,
  playbookId,
  providers,
  legacy,
  canWrite,
}: {
  tenantId: string;
  playbookId: string;
  providers: Array<{
    webhook_id: string;
    name: string;
    enabled: boolean;
    url: string;
    timeout_seconds: number;
  }>;
  legacy: boolean;
  canWrite: boolean;
}) {
  const [tenantSecret, setTenantSecret] =
    useState<WebhookSecretMetadata | null>(null);
  const [override, setOverride] = useState<WebhookSecretMetadata | null>(null);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRevealed(null);
    if (!canWrite) return;
    Promise.all([
      getTenantWebhookSecret(tenantId),
      getPlaybookWebhookSecret(tenantId, playbookId),
    ])
      .then(([tenant, playbook]) => {
        if (!cancelled) {
          setTenantSecret(tenant);
          setOverride(playbook);
        }
      })
      .catch(() => {
        if (!cancelled) toast.error("Failed to load webhook credentials");
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, playbookId, canWrite]);

  async function rotate(scope: "TENANT" | "PLAYBOOK") {
    setBusy(scope);
    setRevealed(null);
    try {
      const result =
        scope === "TENANT"
          ? await rotateTenantWebhookSecret(tenantId)
          : await rotatePlaybookWebhookSecret(tenantId, playbookId);
      if (scope === "TENANT") setTenantSecret(result);
      else setOverride(result);
      setRevealed(result.secret);
      toast.success(
        `${scope === "TENANT" ? "Tenant" : "Playbook"} secret rotated`,
      );
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.detail : "Secret rotation failed",
      );
    } finally {
      setBusy(null);
    }
  }

  async function remove(scope: "TENANT" | "PLAYBOOK") {
    setBusy(scope);
    setRevealed(null);
    try {
      if (scope === "TENANT") {
        setTenantSecret(await deleteTenantWebhookSecret(tenantId));
      } else {
        setOverride(await deletePlaybookWebhookSecret(tenantId, playbookId));
      }
      toast.success("Webhook secret removed");
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.detail : "Secret removal failed",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={PANEL}>
      <h4 className={PANEL_TITLE}>
        <KeyRound className="size-4 text-primary" />
        Signed context providers
      </h4>
      <p className={PANEL_NOTE}>
        {providers.length > 0
          ? `${providers.length} configured provider${providers.length === 1 ? "" : "s"}${legacy ? " · legacy singular configuration" : ""}. All providers share the effective playbook or tenant credential.`
          : "No context provider is configured in this playbook revision."}
      </p>
      {providers.length > 0 ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {providers.map((provider, index) => (
            <div
              key={provider.webhook_id}
              className="rounded-lg bg-[#303030] p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-bold text-foreground">{provider.name}</p>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {provider.webhook_id} · order {index + 1}
                  </p>
                </div>
                <span
                  className={
                    provider.enabled
                      ? "text-xs text-[#4ade80]"
                      : "text-xs text-muted-foreground"
                  }
                >
                  {provider.enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              <p className="mt-3 break-all text-xs text-muted-foreground">
                {provider.url}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {provider.timeout_seconds}s timeout
              </p>
            </div>
          ))}
        </div>
      ) : null}
      {canWrite ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {(
            [
              ["TENANT", "Tenant default", tenantSecret],
              ["PLAYBOOK", "Playbook override", override],
            ] as const
          ).map(([scope, label, metadata]) => (
            <div key={scope} className="rounded-lg bg-[#303030] p-4">
              <p className="font-bold text-foreground">{label}</p>
              <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                {metadata?.configured ? metadata.key_id : "Not configured"}
              </p>
              {scope === "PLAYBOOK" ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Effective scope: {metadata?.effective_scope ?? "NONE"}
                </p>
              ) : null}
              <div className="mt-3 flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void rotate(scope)}
                  disabled={busy !== null}
                >
                  {metadata?.configured ? "Rotate" : "Generate"}
                </Button>
                {metadata?.configured ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void remove(scope)}
                    disabled={busy !== null}
                  >
                    <Trash2 className="size-3.5" /> Remove
                  </Button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">
          Credential metadata is restricted to tenant and platform
          administrators.
        </p>
      )}
      {revealed ? (
        <div className="mt-4 rounded-lg border border-amber-400/30 bg-amber-400/10 p-4">
          <p className="font-bold text-amber-200">Copy this secret now</p>
          <p className="mt-1 text-xs text-amber-100/80">
            It is shown once and is not stored by this page.
          </p>
          <div className="mt-3 flex items-center gap-3">
            <code className="min-w-0 flex-1 break-all rounded bg-[#171717] p-3 text-xs">
              {revealed}
            </code>
            <CopyButton value={revealed} label="webhook secret" />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error(`Could not copy the ${label}`);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="inline-flex h-8 items-center gap-2 rounded-md bg-[#404040] px-3 text-xs font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
    >
      {copied ? (
        <Check className="size-3.5 text-[#4ade80]" />
      ) : (
        <Copy className="size-3.5" />
      )}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function PromptCard({ prompt }: { prompt: string }) {
  const [expanded, setExpanded] = useState(false);
  const text = prompt?.trim() ?? "";
  const isLong = text.length > 320 || text.split("\n").length > 6;

  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className={PANEL_TITLE}>
            <Sparkles className="size-4 text-primary" />
            Prompt
          </h4>
          <p className={PANEL_NOTE}>
            Model / operator instruction text
            {text ? ` · ${text.length.toLocaleString("en-US")} characters` : ""}
          </p>
        </div>
        {text ? <CopyButton value={text} label="prompt" /> : null}
      </div>

      <div className="relative mt-3">
        <p
          className={cn(
            "whitespace-pre-wrap rounded-lg bg-[#171717] p-4 text-sm text-[#d4d4d4]",
            isLong && !expanded && "max-h-48 overflow-hidden",
          )}
        >
          {text || "—"}
        </p>
        {isLong && !expanded ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 rounded-b-lg bg-gradient-to-t from-[#171717] to-transparent" />
        ) : null}
      </div>

      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-3 inline-flex items-center gap-1 text-sm font-bold text-primary underline-offset-4 hover:underline"
        >
          {expanded ? (
            <>
              <ChevronUp className="size-4" />
              Show less
            </>
          ) : (
            <>
              <ChevronDown className="size-4" />
              Show full prompt
            </>
          )}
        </button>
      ) : null}
    </div>
  );
}

function WorkflowNode({
  tone,
  icon,
  title,
  badge,
  centered,
  children,
}: {
  tone: "trigger" | "step";
  icon: React.ReactNode;
  title: string;
  badge?: string;
  centered?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "w-full max-w-[400px] rounded-lg p-4",
        tone === "trigger" ? "bg-primary" : "bg-[#404040]",
        centered && "text-center",
      )}
    >
      <div
        className={cn("flex items-center gap-2", centered && "justify-center")}
      >
        {icon}
        <span className="text-sm font-bold text-white">{title}</span>
        {badge ? (
          <span className="ml-auto rounded bg-[#171717] px-2 py-0.5 font-mono text-[11px] text-[#d4d4d4]">
            {badge}
          </span>
        ) : null}
      </div>
      <div className="mt-2 space-y-1">{children}</div>
    </div>
  );
}

function Connector() {
  return (
    <div className="flex h-10 flex-col items-center justify-center">
      <div className="h-4 w-0.5 bg-[#525252]" />
      <ArrowDown className="size-3.5 text-[#737373]" />
      <div className="h-4 w-0.5 bg-[#525252]" />
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-white/5 py-1.5 last:border-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-bold text-foreground">{value}</dd>
    </div>
  );
}
