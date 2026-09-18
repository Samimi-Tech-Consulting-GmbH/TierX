"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Braces,
  Copy,
  FileText,
  ListX,
  ScanSearch,
} from "lucide-react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api";
import type { DeadLetterRecord } from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import { PANEL, PANEL_NOTE, PANEL_TITLE } from "@/lib/cluster-display";
import { scopedApi, scopedRoutes, type TenantScope } from "@/lib/tenant-scope";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

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
      <div
        className={cn(
          "mt-1 truncate text-sm font-bold text-foreground",
          mono && "font-mono text-xs font-normal",
          tone,
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

export function DeadLetterDetailView({
  tenantId,
  deadLetterId,
  scope,
}: {
  tenantId: string;
  deadLetterId: string;
  scope: TenantScope;
}) {
  const isAdmin = scope === "admin";

  const [record, setRecord] = useState<DeadLetterRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    scopedApi(scope)
      .getDeadLetter(tenantId, deadLetterId)
      .then((r) => {
        if (!cancelled) setRecord(r);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setError("Dead-letter entry not found.");
        } else {
          setError("Failed to load dead-letter entry.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, deadLetterId, scope]);

  function copyJson() {
    if (record?.raw_payload == null) return;
    navigator.clipboard.writeText(JSON.stringify(record.raw_payload, null, 2));
    toast.info("Payload copied");
  }

  const listHref = scopedRoutes(scope, tenantId).deadLetters;

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Loading…
      </div>
    );
  }

  if (error || !record) {
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

  const payloadPretty =
    record.raw_payload != null
      ? JSON.stringify(record.raw_payload, null, 2)
      : null;

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
          <h1 className="text-3xl font-bold tracking-tight">
            Dead letter detail
          </h1>
          <p className="break-all font-mono text-xs text-muted-foreground">
            {record.id}
          </p>
        </div>
        {/* Processing traces live under the platform-admin debug tree. */}
        {isAdmin && record.alert_id ? (
          <Link
            href={`/dashboard/admin/debug/alerts/${encodeURIComponent(record.alert_id)}`}
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
        <p className={PANEL_NOTE}>
          Stored in the tenant&rsquo;s dead_letters collection.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Alert ID" value={record.alert_id ?? "—"} mono />
          <Field
            label="Error type"
            value={record.error_type ?? "—"}
            tone="text-[#f87171]"
          />
          <Field label="Failed stage" value={record.failed_stage ?? "—"} />
          <Field label="Alert type" value={record.alert_type ?? "—"} />
          <Field label="Source system" value={record.source_system ?? "—"} />
          <Field
            label="Tenant ID (payload)"
            value={record.tenant_id ?? "—"}
            mono
          />
          <Field
            label="Received"
            value={formatLocaleDateTime(record.received_at)}
          />
          <Field
            label="Dead-lettered"
            value={formatLocaleDateTime(record.dead_lettered_at)}
          />
          {record.source_alert && (
            <Field label="Source alert" value={record.source_alert} mono />
          )}
          {record.fingerprint && (
            <Field label="Fingerprint" value={record.fingerprint} mono />
          )}
        </div>

        <div className="mt-3 rounded-lg bg-[#404040] px-4 py-3">
          <div className="text-xs text-[#a3a3a3]">Error detail</div>
          <p className="mt-1 whitespace-pre-wrap break-words text-sm text-[#d4d4d4]">
            {record.error_detail ?? "—"}
          </p>
        </div>
      </div>

      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <ListX className="size-4 text-primary" />
          Failed fields
        </h3>
        <p className={PANEL_NOTE}>
          Validation paths or field names reported by the pipeline.
        </p>
        {record.failed_fields && record.failed_fields.length > 0 ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {record.failed_fields.map((field) => (
              <span
                key={String(field)}
                className="rounded-md bg-[#404040] px-3 py-1.5 font-mono text-xs text-[#d4d4d4]"
              >
                {String(field)}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">None recorded.</p>
        )}
      </div>

      <div className={PANEL}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className={PANEL_TITLE}>
              <Braces className="size-4 text-primary" />
              Raw payload
            </h3>
            <p className={PANEL_NOTE}>
              Original message body persisted with this dead-letter row.
            </p>
          </div>
          {payloadPretty ? (
            <button
              type="button"
              onClick={copyJson}
              className="inline-flex h-9 shrink-0 items-center gap-2 rounded-md bg-[#404040] px-4 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
            >
              <Copy className="size-3.5" />
              Copy JSON
            </button>
          ) : null}
        </div>
        {payloadPretty ? (
          <pre className="mt-4 max-h-[min(70vh,720px)] overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[#171717] p-4 font-mono text-xs text-[#d4d4d4]">
            {payloadPretty}
          </pre>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">
            No payload stored.
          </p>
        )}
      </div>
    </div>
  );
}
