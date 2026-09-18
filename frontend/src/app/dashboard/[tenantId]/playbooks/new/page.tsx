"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, FileCode2, Upload } from "lucide-react";
import { toast } from "sonner";
import { parse, stringify } from "yaml";

import {
  appendPlaybookRevisionFromYaml,
  createPlaybookFromYaml,
  getMyTenant,
  getPlaybook,
  listTenantEnrichmentActions,
  ApiError,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { UserRole, type EnrichmentAction } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PANEL, PANEL_NOTE, PANEL_TITLE } from "@/lib/cluster-display";

const EXAMPLE = `prompt: Analyze the alert and suggest next steps.
description: Minimal playbook — actions and alert_types are optional.

# Optional enrichment steps (omit or use [])
# actions:
#   - name: Splunk context
#     adapter: SPLUNK_SPL
#     ...

# Optional routing labels (omit or use [])
# alert_types:
#   - PHISHING

# Optional platform-managed enrichment actions (maximum 10)
# enrichment_actions:
#   - check-server-port
#   - validate-managed-login

# Optional tenant Knowledge Base retrieval
# knowledge_base:
#   enabled: true
#   top_k: 5
#   retrieval_mode: hybrid

is_active: true
is_system: false`;

export default function NewPlaybookPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          Loading…
        </div>
      }
    >
      <NewPlaybookPageHarness />
    </Suspense>
  );
}

function NewPlaybookPageHarness() {
  const params = useParams<{ tenantId: string }>();
  const tenantId = params.tenantId;
  const searchParams = useSearchParams();
  const updatePlaybookId = searchParams.get("updatePlaybook")?.trim() || null;
  const modeKey = `${tenantId}:${updatePlaybookId ?? "create"}`;

  return (
    <NewPlaybookPageContent
      key={modeKey}
      tenantId={tenantId}
      updatePlaybookId={updatePlaybookId}
    />
  );
}

function NewPlaybookPageContent({
  tenantId,
  updatePlaybookId,
}: {
  tenantId: string;
  updatePlaybookId: string | null;
}) {
  const router = useRouter();
  const { user } = useAuth();
  const isUpdate = Boolean(updatePlaybookId);

  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [kbMode, setKbMode] = useState("file");
  const [submitting, setSubmitting] = useState(false);
  const [prefillDone, setPrefillDone] = useState(!isUpdate);
  const [tenantDisplayName, setTenantDisplayName] = useState<
    string | undefined
  >(undefined);
  const [availableActions, setAvailableActions] = useState<EnrichmentAction[]>(
    [],
  );

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setTenantDisplayName(undefined);
    });
    getMyTenant(tenantId)
      .then((t) => {
        if (!cancelled) setTenantDisplayName(t.display_name);
      })
      .catch(() => {
        if (!cancelled) setTenantDisplayName(tenantId);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  useEffect(() => {
    let cancelled = false;
    listTenantEnrichmentActions(tenantId)
      .then((items) => {
        if (!cancelled) setAvailableActions(items);
      })
      .catch(() => {
        if (!cancelled) setAvailableActions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  useEffect(() => {
    if (!updatePlaybookId) {
      return;
    }
    let cancelled = false;
    getPlaybook(tenantId, updatePlaybookId)
      .then((doc) => {
        if (!cancelled) setName(doc.playbook_name);
      })
      .catch(() => {
        if (!cancelled) {
          toast.error("Could not load playbook to update");
          router.replace(`/dashboard/${tenantId}/playbooks`);
        }
      })
      .finally(() => {
        if (!cancelled) setPrefillDone(true);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, updatePlaybookId, router]);

  const canWrite =
    user?.role === UserRole.PLATFORM_ADMIN ||
    user?.role === UserRole.TENANT_ADMIN;

  function playbookHref(playbookId: string): string {
    return `/dashboard/${tenantId}/playbooks?playbook=${encodeURIComponent(playbookId)}`;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      toast.error("Choose a .yml or .yaml file");
      return;
    }
    if (isUpdate && !updatePlaybookId) {
      toast.error("Missing playbook id");
      return;
    }
    setSubmitting(true);
    try {
      let uploadFile = file;
      if (kbMode !== "file") {
        const contents = parse(await file.text(), { maxAliasCount: 20 });
        if (!contents || typeof contents !== "object" || Array.isArray(contents)) {
          throw new Error("Playbook YAML must be an object");
        }
        contents.knowledge_base = { ...contents.knowledge_base, enabled: true,
          top_k: contents.knowledge_base?.top_k ?? 5, retrieval_mode: kbMode };
        uploadFile = new File([stringify(contents)], file.name, { type: file.type });
      }
      if (isUpdate && updatePlaybookId) {
        const updated = await appendPlaybookRevisionFromYaml(
          tenantId,
          updatePlaybookId,
          name,
          uploadFile,
        );
        toast.success(`Version ${updated.version} saved`);
        router.push(playbookHref(updated.playbook_id));
      } else {
        const created = await createPlaybookFromYaml(tenantId, name, uploadFile);
        toast.success("Playbook created");
        router.push(playbookHref(created.playbook_id));
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.detail
          : isUpdate
            ? "Failed to save new version"
            : "Failed to create playbook";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  }

  const backHref =
    isUpdate && updatePlaybookId
      ? playbookHref(updatePlaybookId)
      : `/dashboard/${tenantId}/playbooks`;

  if (!canWrite) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Not allowed</h3>
        <p className={PANEL_NOTE}>
          Only tenant administrators or platform admins can create playbooks.
        </p>
        <Link
          href={`/dashboard/${tenantId}/playbooks`}
          className="mt-4 inline-flex h-10 items-center rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90"
        >
          Back to list
        </Link>
      </div>
    );
  }

  if (
    user &&
    user.role !== UserRole.PLATFORM_ADMIN &&
    user.tenant_id !== tenantId
  ) {
    return (
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>Access denied</h3>
      </div>
    );
  }

  if (!prefillDone) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
        Loading playbook…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3">
        <Link
          href={backHref}
          className="mt-1 inline-flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
          aria-label="Back"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            {isUpdate ? "Update playbook" : "New playbook"}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {tenantDisplayName === undefined ? "…" : tenantDisplayName}
            {isUpdate
              ? " · a new stored version keeps the same playbook id"
              : null}
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>
            <Upload className="size-4 text-primary" />
            Upload YAML
          </h3>
          <div className="mt-1 space-y-2 text-sm text-muted-foreground">
            <p>
              Enter the playbook <strong>name</strong> below; it is not read
              from the YAML file.
            </p>
            {isUpdate ? (
              <p>
                Submitting creates a new stored version; older revisions stay
                listed in the playbook&apos;s version history.
              </p>
            ) : null}
            <p>
              Required YAML fields:{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">prompt</code>,{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">
                description
              </code>
              ,{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">
                is_active
              </code>
              , and{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">
                is_system
              </code>
              . Optional:{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">actions</code>{" "}
              (array of enrichment steps),{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">
                alert_types
              </code>
              , and{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">
                enrichment_actions
              </code>
              , and{" "}
              <code className="rounded bg-[#404040] px-1 text-xs">
                knowledge_base
              </code>
              . Action codes must be enabled for this tenant.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="mt-5 space-y-5">
            <div className="space-y-2">
              <Label htmlFor="pb-name" className="text-xs text-[#a3a3a3]">
                Playbook name
              </Label>
              <Input
                id="pb-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Phishing escalation"
                required
                maxLength={512}
                className="h-10 bg-[#404040]"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="pb-file" className="text-xs text-[#a3a3a3]">
                YAML file
              </Label>
              <Input
                id="pb-file"
                type="file"
                accept=".yml,.yaml,application/x-yaml,text/yaml"
                required
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="h-auto cursor-pointer bg-[#404040] py-3"
              />
            </div>

            <label className="block space-y-2 text-sm">
              Knowledge Base retrieval for this revision
              <select className="mt-2 block rounded border bg-background p-2" value={kbMode}
                onChange={(event) => setKbMode(event.target.value)}>
                <option value="file">Keep uploaded YAML configuration</option>
                <option value="deterministic">Enable deterministic retrieval</option>
                <option value="hybrid">Enable hybrid retrieval (Mem0 + deterministic)</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-5 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              <Upload className="size-4" />
              {submitting
                ? isUpdate
                  ? "Saving…"
                  : "Creating…"
                : isUpdate
                  ? "Save new version"
                  : "Create playbook"}
            </button>
          </form>
        </div>

        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>
            <FileCode2 className="size-4 text-primary" />
            Minimal example
          </h3>
          <p className={PANEL_NOTE}>
            Copy this as a starting point for the uploaded file.
          </p>
          <pre className="mt-4 overflow-x-auto whitespace-pre-wrap rounded-lg bg-[#171717] p-4 font-mono text-xs text-[#d4d4d4]">
            {EXAMPLE}
          </pre>
          <div className="mt-5 border-t border-white/5 pt-4">
            <h4 className="text-sm font-semibold">Authorized action codes</h4>
            {availableActions.length ? (
              <ul className="mt-2 space-y-2 text-sm">
                {availableActions.map((action) => (
                  <li
                    key={action.action_code}
                    className="rounded bg-[#171717] p-3"
                  >
                    <code>{action.action_code}</code>
                    <span className="ml-2 text-muted-foreground">
                      {action.name}
                    </span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      · timeout {action.timeout_seconds}s
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                No platform-managed enrichment actions are enabled for this
                tenant.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
