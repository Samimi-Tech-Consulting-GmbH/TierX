"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  Clock3,
  Copy,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Route,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { ApiError, getDebugTrace } from "@/lib/api";
import type { ProcessingTraceDetail, ProcessingTraceSpan } from "@/lib/types";
import { formatLocaleDateTime } from "@/lib/datetime";
import { formatDurationMs } from "@/lib/duration";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
  runStateTone,
} from "@/lib/cluster-display";
import { cn } from "@/lib/utils";

const EXPECTED_STAGES = [
  "INGESTION",
  "VALIDATION",
  "NORMALIZATION",
  "FINGERPRINT",
  "ENRICHMENT",
  "ENRICHMENT_ACTION",
  "CORRELATION",
  "ANALYSIS",
] as const;

/** Adds the two states the shared run-state map does not carry. */
function traceStateTone(state: string): string {
  if (state === "STALLED") return "bg-destructive";
  if (state === "NOT_REACHED") return "bg-[#525252]";
  return runStateTone(state);
}

function StageIcon({ outcome }: { outcome: string }) {
  if (outcome === "SUCCEEDED")
    return <CheckCircle2 className="size-5 text-[#4ade80]" />;
  if (outcome === "FAILED" || outcome === "STALLED")
    return <XCircle className="size-5 text-[#f87171]" />;
  if (outcome === "RUNNING")
    return <LoaderCircle className="size-5 animate-spin text-primary" />;
  return <Clock3 className="size-5 text-muted-foreground" />;
}

function CopyButton({
  value,
  label,
  compact,
}: {
  value: string;
  label: string;
  compact?: boolean;
}) {
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
      title={`Copy ${label}`}
      className={cn(
        "inline-flex items-center gap-2 rounded-md bg-[#404040] font-bold text-foreground transition-colors hover:bg-[#4a4a4a]",
        compact ? "h-8 px-3 text-xs" : "h-10 px-5 text-sm",
      )}
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

function JsonBlock({ value }: { value: unknown }) {
  if (value == null) {
    return <p className="text-sm text-muted-foreground">Not recorded.</p>;
  }
  return (
    <pre className="max-h-[460px] overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[#171717] p-4 font-mono text-xs text-[#d4d4d4]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Disclosure({
  title,
  open,
  children,
}: {
  title: string;
  open?: boolean;
  children: React.ReactNode;
}) {
  return (
    <details className="rounded-lg bg-[#171717]/60 p-4" open={open}>
      <summary className="cursor-pointer text-sm font-bold text-foreground">
        {title}
      </summary>
      {children}
    </details>
  );
}

function SpanCard({ span }: { span: ProcessingTraceSpan }) {
  const providerDecisions =
    span.stage === "ENRICHMENT" &&
    Array.isArray(span.decisions?.playbook_context_webhooks)
      ? span.decisions.playbook_context_webhooks.filter(
          (item): item is Record<string, unknown> =>
            item != null && typeof item === "object" && !Array.isArray(item),
        )
      : [];

  return (
    <div
      className={cn(
        PANEL,
        span.outcome === "FAILED" && "ring-1 ring-destructive/40",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-white/5 pb-4">
        <div className="flex items-center gap-3">
          <StageIcon outcome={span.outcome} />
          <div>
            <h4 className="text-base font-bold text-foreground">
              {span.stage.replaceAll("_", " ")}
            </h4>
            <p className="mt-1 text-sm text-muted-foreground">
              {span.service} ·{" "}
              {span.duration_ms != null
                ? formatDurationMs(span.duration_ms)
                : "in progress"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn(PILL, traceStateTone(span.outcome))}>
            {span.outcome}
          </span>
          <CopyButton
            value={JSON.stringify(span, null, 2)}
            label="stage trace"
            compact
          />
        </div>
      </div>

      <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <span className="text-muted-foreground">Started: </span>
          <span className="text-foreground">
            {formatLocaleDateTime(span.started_at)}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Release: </span>
          <span className="font-mono text-xs text-[#d4d4d4]">
            {span.release_version
              ? `v${span.release_version}`
              : "Version unavailable"}
            {" · "}
            {span.release_sha ? span.release_sha.slice(0, 7) : "no SHA"}
          </span>
        </div>
      </div>

      {span.error ? (
        <div className="mt-4 rounded-lg bg-destructive/10 p-4 ring-1 ring-destructive/30">
          <div className="mb-2 text-sm font-bold text-destructive">Failure</div>
          <JsonBlock value={span.error} />
        </div>
      ) : null}

      {providerDecisions.length > 0 ? (
        <div className="mt-4">
          <div className="mb-2 text-xs font-bold uppercase text-muted-foreground">
            Context provider outcomes
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {providerDecisions.map((provider, index) => (
              <div
                key={String(provider.delivery_id ?? provider.webhook_id ?? index)}
                className="rounded-lg bg-[#303030] p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-bold text-foreground">
                      {String(provider.webhook_name ?? provider.webhook_id ?? `Provider ${index + 1}`)}
                    </p>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">
                      {String(provider.webhook_id ?? "legacy-context")} · order{" "}
                      {Number(provider.config_order ?? index) + 1}
                    </p>
                  </div>
                  <span className={cn(PILL, runStateTone(String(provider.status ?? "SKIPPED")))}>
                    {String(provider.status ?? "SKIPPED")}
                  </span>
                </div>
                <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                  <span>
                    Duration: {provider.duration_ms == null ? "—" : formatDurationMs(Number(provider.duration_ms))}
                  </span>
                  <span>
                    Credential: {String(provider.effective_credential_scope ?? "—")}
                  </span>
                  <span className="break-all font-mono sm:col-span-2">
                    Delivery: {String(provider.delivery_id ?? "—")}
                  </span>
                  {provider.error_type ? (
                    <span className="text-[#f87171] sm:col-span-2">
                      Failure: {String(provider.error_type)}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        <Disclosure
          title="Checks and decisions"
          open={
            span.stage === "ENRICHMENT" ||
            span.stage === "ENRICHMENT_ACTION" ||
            span.stage === "CORRELATION" ||
            span.stage === "ANALYSIS"
          }
        >
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-bold uppercase text-muted-foreground">
                Checks
              </div>
              <JsonBlock value={span.checks} />
            </div>
            <div>
              <div className="mb-2 text-xs font-bold uppercase text-muted-foreground">
                Decisions
              </div>
              <JsonBlock value={span.decisions} />
            </div>
          </div>
        </Disclosure>

        <Disclosure title="Input and output snapshots">
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-bold uppercase text-muted-foreground">
                Input
              </div>
              <JsonBlock value={span.input_snapshot} />
            </div>
            <div>
              <div className="mb-2 text-xs font-bold uppercase text-muted-foreground">
                Output
              </div>
              <JsonBlock value={span.output_snapshot} />
            </div>
          </div>
        </Disclosure>
      </div>
    </div>
  );
}

export default function ProcessingTraceDetailPage() {
  const { alertId } = useParams<{ alertId: string }>();
  const [detail, setDetail] = useState<ProcessingTraceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDetail(await getDebugTrace(alertId));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError("Trace unavailable — this alert may predate instrumentation.");
      } else {
        setError("Failed to load processing trace.");
      }
    } finally {
      setLoading(false);
    }
  }, [alertId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (
      !detail ||
      !["RUNNING", "STALLED"].includes(detail.summary.terminal_state)
    )
      return;
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [detail, load]);

  const stages = useMemo(() => {
    const byName = new Map(
      (detail?.spans ?? []).map((span) => [span.stage, span]),
    );
    const failedSequence = detail?.spans.find(
      (span) => span.outcome === "FAILED",
    )?.sequence;
    return EXPECTED_STAGES.map((stage, index) => ({
      stage,
      state:
        byName.get(stage)?.outcome ??
        (failedSequence != null && failedSequence < (index + 1) * 10
          ? "NOT_REACHED"
          : "PENDING"),
    }));
  }, [detail]);

  if (loading && !detail) {
    return (
      <div className="flex h-48 items-center justify-center gap-2 text-muted-foreground">
        <LoaderCircle className="size-5 animate-spin" />
        Loading trace…
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="space-y-6">
        <BackLink />
        <div className={PANEL}>
          <h3 className={PANEL_TITLE}>Trace unavailable</h3>
          <p className={PANEL_NOTE}>{error ?? "No trace for this alert."}</p>
        </div>
      </div>
    );
  }

  const { summary, spans } = detail;
  const releaseLabel = summary.mixed_releases
    ? "Mixed versions"
    : `${
        summary.release_version
          ? `v${summary.release_version}`
          : "Version unavailable"
      } · ${summary.release_sha ? summary.release_sha.slice(0, 7) : "no SHA"}`;
  const domainHref = summary.tenant_id
    ? `/dashboard/admin/tenants/${summary.tenant_id}/alerts/${summary.alert_id}`
    : null;
  const deadLetterSpan = spans.find((span) => span.stage === "DEAD_LETTER");
  const deadLetterSnapshot = deadLetterSpan?.output_snapshot as
    { value?: { dead_letter_id?: string } } | undefined;
  const deadLetterId = deadLetterSnapshot?.value?.dead_letter_id;
  const deadLetterHref =
    summary.tenant_id && deadLetterId
      ? `/dashboard/admin/tenants/${summary.tenant_id}/dead-letters/${deadLetterId}`
      : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <BackLink />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-bold tracking-tight">
                Alert processing trace
              </h1>
              <span
                className={cn(PILL, traceStateTone(summary.terminal_state))}
              >
                {summary.terminal_state}
              </span>
            </div>
            <p className="mt-2 break-all font-mono text-sm text-muted-foreground">
              {summary.alert_id}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex h-10 items-center gap-2 rounded-md bg-[#404040] px-5 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a] disabled:opacity-40"
          >
            <RefreshCw className={cn("size-4", loading && "animate-spin")} />
            Refresh
          </button>
          <CopyButton
            value={JSON.stringify(detail, null, 2)}
            label="versioned trace"
          />
        </div>
      </div>

      <div className={PANEL}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className={PANEL_TITLE}>
              <Route className="size-4 text-primary" />
              Pipeline progress
            </h3>
            <p className={PANEL_NOTE}>
              {summary.alert_type ?? "Unknown alert type"} ·{" "}
              {summary.source_system ?? "Unknown source"} · {spans.length} stage
              {spans.length === 1 ? "" : "s"} recorded
            </p>
          </div>
          <span className="rounded-md bg-[#404040] px-3 py-1 font-mono text-xs text-[#d4d4d4]">
            {releaseLabel}
          </span>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3 xl:grid-cols-7">
          {stages.map(({ stage, state }) => (
            <div key={stage} className="rounded-lg bg-[#404040]/50 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <StageIcon outcome={state} />
                <span
                  className={cn(
                    PILL,
                    "px-2 py-0.5 text-[10px]",
                    traceStateTone(state),
                  )}
                >
                  {state.replaceAll("_", " ")}
                </span>
              </div>
              <div className="text-sm font-bold text-foreground">
                {stage.replaceAll("_", " ")}
              </div>
            </div>
          ))}
        </div>

        {domainHref || deadLetterHref ? (
          <div className="mt-5 flex flex-wrap gap-2 border-t border-white/5 pt-4">
            {domainHref ? (
              <Link
                href={domainHref}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-[#404040] px-4 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
              >
                <ExternalLink className="size-4" />
                Open stored alert
              </Link>
            ) : null}
            {deadLetterHref ? (
              <Link
                href={deadLetterHref}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-[#404040] px-4 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
              >
                <ExternalLink className="size-4" />
                Open dead letter
              </Link>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="space-y-4">
        {spans.map((span) => (
          <SpanCard key={span.span_id} span={span} />
        ))}
      </div>

      <div className="rounded-lg bg-[#d97706]/10 p-4 ring-1 ring-[#d97706]/30">
        <div className="text-sm font-bold text-[#fbbf24]">
          Current pipeline boundary
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {detail.pipeline_boundary}
        </p>
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/dashboard/admin/debug"
      aria-label="Back to processing debug"
      className="mt-1 inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-white/5 hover:text-foreground"
    >
      <ArrowLeft className="size-4" />
    </Link>
  );
}
