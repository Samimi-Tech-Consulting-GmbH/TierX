"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  FileCode2,
  History,
  ListChecks,
  Pencil,
} from "lucide-react";
import { toast } from "sonner";

import {
  getAlertTypeSchemaById,
  listAlertTypeSchemaHistory,
  activateAlertTypeSchema,
  ApiError,
} from "@/lib/api";
import type { AlertTypeSchemaDocument } from "@/lib/types";
import {
  normalizeSchemaFields,
  type NormalizedSchemaFieldRow,
} from "@/lib/alert-type-schema-fields";
import { formatLocaleDateTime } from "@/lib/datetime";
import {
  PANEL,
  PANEL_NOTE,
  PANEL_TITLE,
  PILL,
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

const FIELD_PREVIEW_COUNT = 6;

export interface SchemaDetail {
  tenantId: string;
  canWrite: boolean;
  displayDoc: AlertTypeSchemaDocument | null;
  history: AlertTypeSchemaDocument[];
  selectedVersionId: string;
  selectVersion: (schemaId: string) => void;
  activeProduction: AlertTypeSchemaDocument | null;
  fieldRows: NormalizedSchemaFieldRow[];
  mappingKeys: Set<string>;
  loading: boolean;
  activateOpen: boolean;
  setActivateOpen: (open: boolean) => void;
  activating: boolean;
  confirmActivate: () => Promise<void>;
}

export function useSchemaDetail({
  tenantId,
  schemaId,
  canWrite,
  onChanged,
}: {
  tenantId: string;
  schemaId: string | null;
  canWrite: boolean;
  onChanged?: () => void;
}): SchemaDetail {
  const [bootDoc, setBootDoc] = useState<AlertTypeSchemaDocument | null>(null);
  const [history, setHistory] = useState<AlertTypeSchemaDocument[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [activateOpen, setActivateOpen] = useState(false);
  const [activating, setActivating] = useState(false);

  const displayDoc = useMemo(() => {
    const fromHist = history.find((h) => h.schema_id === selectedVersionId);
    if (fromHist) return fromHist;
    if (bootDoc?.schema_id === selectedVersionId) return bootDoc;
    return bootDoc;
  }, [history, selectedVersionId, bootDoc]);

  const activeProduction = useMemo(
    () => history.find((h) => h.is_active) ?? null,
    [history],
  );

  const fieldRows = useMemo(
    () => (displayDoc ? normalizeSchemaFields(displayDoc) : []),
    [displayDoc],
  );

  const mappingKeys = useMemo(() => {
    const m = displayDoc?.field_mapping;
    if (!m || typeof m !== "object") return new Set<string>();
    return new Set(Object.keys(m as Record<string, string>));
  }, [displayDoc?.field_mapping]);

  const reload = useCallback(async () => {
    if (!schemaId) return;
    const doc = await getAlertTypeSchemaById(tenantId, schemaId);
    setBootDoc(doc);
    const hist = await listAlertTypeSchemaHistory(tenantId, doc.alert_type);
    setHistory(hist);
    setSelectedVersionId((current) =>
      hist.some((h) => h.schema_id === current) ? current : doc.schema_id,
    );
  }, [tenantId, schemaId]);

  useEffect(() => {
    if (!schemaId) {
      setBootDoc(null);
      setHistory([]);
      setSelectedVersionId("");
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setBootDoc(null);
    setHistory([]);
    getAlertTypeSchemaById(tenantId, schemaId)
      .then(async (doc) => {
        if (cancelled) return;
        setBootDoc(doc);
        setSelectedVersionId(doc.schema_id);
        const hist = await listAlertTypeSchemaHistory(tenantId, doc.alert_type);
        if (cancelled) return;
        setHistory(hist);
      })
      .catch(() => {
        if (!cancelled) toast.error("Schema not found");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, schemaId]);

  const confirmActivate = useCallback(async () => {
    if (!displayDoc || !canWrite || displayDoc.is_active) return;
    setActivating(true);
    try {
      await activateAlertTypeSchema(
        tenantId,
        displayDoc.alert_type,
        displayDoc.schema_id,
      );
      toast.success(`Version ${displayDoc.version} is now active.`);
      setActivateOpen(false);
      await reload();
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detail : "Activation failed");
    } finally {
      setActivating(false);
    }
  }, [displayDoc, canWrite, tenantId, reload, onChanged]);

  return {
    tenantId,
    canWrite,
    displayDoc,
    history,
    selectedVersionId,
    selectVersion: setSelectedVersionId,
    activeProduction,
    fieldRows,
    mappingKeys,
    loading,
    activateOpen,
    setActivateOpen,
    activating,
    confirmActivate,
  };
}

export function SchemaDetailRail({ detail }: { detail: SchemaDetail }) {
  const {
    tenantId,
    canWrite,
    displayDoc,
    history,
    selectedVersionId,
    selectVersion,
    activeProduction,
    fieldRows,
    loading,
    activateOpen,
    setActivateOpen,
    activating,
    confirmActivate,
  } = detail;

  const backHref = `/dashboard/${tenantId}/schema-registry`;
  const cloneFromId =
    activeProduction?.schema_id ?? displayDoc?.schema_id ?? "";

  if (loading && !displayDoc) {
    return (
      <div className="space-y-6">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className={cn(PANEL, "space-y-3")}>
            {Array.from({ length: 4 }).map((__, row) => (
              <div
                key={row}
                className="h-10 animate-pulse rounded bg-white/5"
              />
            ))}
          </div>
        ))}
      </div>
    );
  }
  if (!displayDoc) return null;

  return (
    <div className="space-y-6">
      <div className={PANEL}>
        <h3 className={PANEL_TITLE}>
          <FileCode2 className="size-4 text-primary" />
          Schema details
        </h3>

        <div className="mt-4 flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary">
            <FileCode2 className="size-4 text-primary-foreground" />
          </span>
          <div className="min-w-0">
            <p
              className="truncate font-mono text-sm font-bold text-foreground"
              title={displayDoc.alert_type}
            >
              {displayDoc.alert_type}
            </p>
            <p className="mt-0.5 text-xs text-[#a3a3a3]">
              {displayDoc.description || "No description"}
            </p>
          </div>
        </div>

        <dl className="mt-4 space-y-2">
          <Row label="Viewing version">
            <span className="font-bold tabular-nums text-foreground">
              v{displayDoc.version}
            </span>
          </Row>
          <Row label="Status">
            <span
              className={cn(
                PILL,
                displayDoc.is_active ? "bg-[#16a34a]" : "bg-[#525252]",
              )}
            >
              {displayDoc.is_active ? "Active" : "Draft"}
            </span>
          </Row>
          <Row label="Active version">
            {activeProduction ? (
              <span className={cn(PILL, "bg-[#16a34a]")}>
                v{activeProduction.version}
              </span>
            ) : (
              <span className={cn(PILL, "bg-[#525252]")}>None</span>
            )}
          </Row>
          <Row label="Playbook">
            <span className="text-sm text-[#d4d4d4]">
              {displayDoc.playbook_id || "—"}
            </span>
          </Row>
          <Row label="Created">
            <span className="text-sm text-[#d4d4d4]">
              {formatLocaleDateTime(displayDoc.created_at)}
            </span>
          </Row>
          <Row label="Last modified">
            <span className="text-sm text-[#d4d4d4]">
              {formatLocaleDateTime(displayDoc.updated_at)}
            </span>
          </Row>
        </dl>

        {canWrite ? (
          <div className="mt-5 flex flex-wrap gap-2">
            <Link
              href={`${backHref}/new?cloneFrom=${encodeURIComponent(cloneFromId)}`}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-bold text-primary-foreground transition-opacity hover:opacity-90"
            >
              <Pencil className="size-4" />
              Create new version
            </Link>
            {!displayDoc.is_active ? (
              <button
                type="button"
                onClick={() => setActivateOpen(true)}
                className="h-10 rounded-md bg-[#404040] px-4 text-sm font-bold text-foreground transition-colors hover:bg-[#4a4a4a]"
              >
                Activate this version
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className={PANEL}>
        <div className="flex flex-wrap items-center gap-3">
          <h3 className={PANEL_TITLE}>
            <ListChecks className="size-4 text-primary" />
            Schema fields
          </h3>
          <span className="text-sm text-muted-foreground">
            {fieldRows.length}
          </span>
        </div>
        <p className={PANEL_NOTE}>
          {(displayDoc.fields?.length ?? 0) > 0
            ? "ECS paths mapped by this version, with the type recorded in YAML."
            : "ECS paths mapped by this version. This version records no field types, so the types shown are inferred from the ECS path."}
        </p>

        {fieldRows.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">
            No field mappings for this version.
          </p>
        ) : (
          <>
            <ul className="mt-4 space-y-2">
              {fieldRows.slice(0, FIELD_PREVIEW_COUNT).map((row) => (
                <li
                  key={row.field_path}
                  className="flex items-center gap-3 rounded-md bg-[#171717] px-4 py-2.5"
                >
                  <span
                    className="min-w-0 flex-1 truncate font-mono text-xs text-foreground"
                    title={row.field_path}
                  >
                    {row.field_path}
                  </span>
                  <span className="shrink-0 text-xs text-[#737373]">
                    {row.field_type}
                  </span>
                </li>
              ))}
            </ul>

            {fieldRows.length > FIELD_PREVIEW_COUNT ? (
              <Link
                href={`${backHref}/${encodeURIComponent(displayDoc.schema_id)}`}
                className="mt-4 inline-flex items-center gap-2 rounded-sm text-sm font-bold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                View all {fieldRows.length} fields
                <ArrowRight className="size-3.5" />
              </Link>
            ) : null}
          </>
        )}
      </div>

      <div className={PANEL}>
        <div className="flex flex-wrap items-center gap-3">
          <h3 className={PANEL_TITLE}>
            <History className="size-4 text-primary" />
            Version history
          </h3>
          <span className="text-sm text-muted-foreground">
            {history.length}
          </span>
        </div>
        <p className={PANEL_NOTE}>
          Every version stored for this alert type. Select one to inspect its
          fields below.
        </p>

        <div className="mt-4 max-h-[320px] space-y-2 overflow-y-auto pr-1">
          {history.map((h) => {
            const selected = h.schema_id === selectedVersionId;
            return (
              <button
                key={h.schema_id}
                type="button"
                onClick={() => selectVersion(h.schema_id)}
                aria-current={selected ? "true" : undefined}
                className={cn(
                  "w-full rounded-lg border px-4 py-3 text-left transition-colors",
                  selected
                    ? "border-[#d60c89] bg-[#d60c89]/20"
                    : "border-transparent bg-[#404040] hover:bg-[#4a4a4a]",
                )}
              >
                <span className="flex items-center gap-3">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "size-2 shrink-0 rounded-full",
                      h.is_active ? "bg-primary" : "bg-[#525252]",
                    )}
                  />
                  <span className="flex-1 text-sm font-bold tabular-nums text-foreground">
                    v{h.version}
                  </span>
                  <span
                    className={cn(
                      PILL,
                      h.is_active ? "bg-[#16a34a]" : "bg-[#525252]",
                    )}
                  >
                    {h.is_active ? "Active" : "Draft"}
                  </span>
                </span>
                {/* Second line: the rail is too narrow to keep this inline. */}
                <span className="mt-1 block pl-5 text-xs text-[#a3a3a3]">
                  {formatLocaleDateTime(h.updated_at)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <Dialog open={activateOpen} onOpenChange={setActivateOpen}>
        <DialogContent className="sm:max-w-md" showCloseButton>
          <DialogHeader>
            <DialogTitle>Activate version {displayDoc.version}?</DialogTitle>
            <DialogDescription className="text-pretty">
              {activeProduction &&
              activeProduction.schema_id !== displayDoc.schema_id ? (
                <>
                  Activating this version will deactivate version{" "}
                  <span className="font-medium tabular-nums">
                    {activeProduction.version}
                  </span>
                  . All new alerts will be validated against the new schema.
                </>
              ) : displayDoc.is_active ? (
                <>This version is already active.</>
              ) : (
                <>
                  No version is currently active for this alert type. Activating
                  will make{" "}
                  <span className="font-medium tabular-nums">
                    {displayDoc.version}
                  </span>{" "}
                  the active schema. All new alerts will be validated against
                  it.
                </>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setActivateOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={activating}
              onClick={() => void confirmActivate()}
            >
              {activating ? "Activating…" : "Activate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function SchemaFieldsPanel({
  detail,
  query = "",
}: {
  detail: SchemaDetail;
  query?: string;
}) {
  const { displayDoc, fieldRows } = detail;

  const term = query.trim().toLowerCase();
  const rows = term
    ? fieldRows.filter((row) =>
        [row.field_path, row.source_path, row.field_type, row.description]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(term)),
      )
    : fieldRows;

  if (!displayDoc) return null;

  return (
    <>
      <div className={PANEL}>
        <div className="flex flex-wrap items-center gap-3">
          <h3 className={PANEL_TITLE}>
            <ListChecks className="size-4 text-primary" />
            Fields
          </h3>
          <span className="text-sm text-muted-foreground">
            {term ? `${rows.length} of ${fieldRows.length}` : fieldRows.length}
          </span>
        </div>
        <p className={PANEL_NOTE}>
          Each row is one ECS path from <code>field_mapping</code> with its
          ingest/source path and optional metadata merged from{" "}
          <code>fields[]</code> in YAML.
        </p>

        <div className="mt-4 overflow-x-auto rounded-lg">
          {fieldRows.length === 0 ? (
            <p className="p-10 text-center text-sm text-muted-foreground">
              No field mappings for this version.
            </p>
          ) : rows.length === 0 ? (
            <p className="p-10 text-center text-sm text-muted-foreground">
              No fields match “{query.trim()}”.
            </p>
          ) : (
            <table className="w-full min-w-[900px] text-left">
              <thead className={TABLE_HEAD}>
                <tr>
                  <th className="px-4 py-3">Field path (ECS)</th>
                  <th className="px-4 py-3">Source path (ingest)</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Required</th>
                  <th className="px-4 py-3">Indexed</th>
                  <th className="px-4 py-3">Embeddable</th>
                  <th className="px-4 py-3">Description</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.field_path} className={TABLE_ROW}>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-foreground">
                      {row.field_path}
                    </td>
                    <td
                      className="max-w-[220px] truncate whitespace-nowrap px-4 py-3 font-mono text-xs text-muted-foreground"
                      title={row.source_path ?? undefined}
                    >
                      {row.source_path ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-md bg-[#404040] px-2.5 py-1 text-xs text-[#d4d4d4]">
                        {row.field_type}
                      </span>
                    </td>
                    <Flag on={row.is_required} />
                    <Flag on={row.is_indexed} />
                    <Flag on={row.is_embeddable} />
                    <td className="max-w-xs px-4 py-3 text-sm text-muted-foreground">
                      {row.description || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

export function SchemaCriticalFieldsPanel({
  detail,
}: {
  detail: SchemaDetail;
}) {
  const { displayDoc, mappingKeys } = detail;

  if (!displayDoc) return null;

  return (
    <div className={PANEL}>
      <h3 className={PANEL_TITLE}>
        <ListChecks className="size-4 text-primary" />
        Critical fields
      </h3>
      <p className={PANEL_NOTE}>
        ECS paths the pipeline treats as mandatory for this alert type. If a
        critical path is missing from <code>field_mapping</code> for this
        version, normalization can flag a gap when alerts omit those fields.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {(displayDoc.critical_fields ?? []).length === 0 ? (
          <span className="text-sm text-muted-foreground">None defined.</span>
        ) : (
          (displayDoc.critical_fields ?? []).map((path) => {
            const inMapping = mappingKeys.has(path);
            return (
              <span
                key={path}
                title={
                  inMapping
                    ? "Present in field_mapping for this version"
                    : "Missing from field_mapping — normalization may warn when data is absent"
                }
                className={cn(
                  "rounded-md px-3 py-1.5 font-mono text-xs",
                  inMapping
                    ? "bg-[#404040] text-[#d4d4d4]"
                    : "bg-destructive text-white",
                )}
              >
                {path}
              </span>
            );
          })
        )}
      </div>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/5 pb-2 last:border-0 last:pb-0">
      <dt className="text-sm text-[#a3a3a3]">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

function Flag({ on }: { on: boolean }) {
  return (
    <td className="px-4 py-3">
      <span
        className={cn(
          "rounded-md px-2.5 py-1 text-xs font-bold",
          on ? "bg-[#404040] text-foreground" : "bg-transparent text-[#737373]",
        )}
      >
        {on ? "Yes" : "No"}
      </span>
    </td>
  );
}
