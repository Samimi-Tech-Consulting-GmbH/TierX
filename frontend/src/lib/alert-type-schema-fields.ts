import type { AlertTypeSchemaDocument } from "@/lib/types";

export interface NormalizedSchemaFieldRow {
  field_path: string;
  field_type: string;
  is_required: boolean;
  is_indexed: boolean;
  is_embeddable: boolean;
  description: string;
  source_path?: string;
}

function asBool(v: unknown, defaultVal: boolean): boolean {
  if (typeof v === "boolean") return v;
  if (v === "true" || v === true) return true;
  if (v === "false" || v === false) return false;
  return defaultVal;
}

function asStr(v: unknown, fallback = ""): string {
  if (v === null || v === undefined) return fallback;
  return String(v);
}

/**
 * When YAML only provides field_mapping (no per-field type in `fields[]`), infer a display type
 * from common ECS path patterns. Overrides still come from extended field definitions.
 */
function inferEcsFieldType(ecsPath: string): string {
  const p = ecsPath.trim().toLowerCase();
  if (!p) return "string";

  if (p.endsWith(".port") || p.endsWith(".pid") || p.endsWith(".pid_ns")) {
    return "long";
  }
  if (
    p.endsWith(".ip") ||
    p.endsWith(".nat.ip") ||
    p.endsWith(".broadcast") ||
    p.endsWith(".gateway")
  ) {
    return "ip";
  }
  if (
    p === "@timestamp" ||
    p === "event.created" ||
    p.endsWith("._time") ||
    (p.startsWith("event.") && p.endsWith(".created"))
  ) {
    return "date";
  }
  if (p.endsWith(".severity") || p.endsWith(".risk_score") || p.endsWith(".confidence")) {
    return "long";
  }
  if (p.includes(".hash.") || p.endsWith(".hash")) {
    return "keyword";
  }
  if (
    p.endsWith(".bytes") ||
    p.endsWith(".packets") ||
    p.endsWith(".size") ||
    (p.includes("file.") && p.endsWith(".size"))
  ) {
    return "long";
  }

  return "string";
}

/** Merge field_mapping (ECS → source) with optional extended `fields` definitions. */
export function normalizeSchemaFields(doc: AlertTypeSchemaDocument): NormalizedSchemaFieldRow[] {
  const critical = new Set(doc.critical_fields ?? []);
  const mapping =
    doc.field_mapping && typeof doc.field_mapping === "object"
      ? (doc.field_mapping as Record<string, string>)
      : {};

  const byPath = new Map<string, NormalizedSchemaFieldRow>();

  for (const [ecsPath, sourcePath] of Object.entries(mapping)) {
    byPath.set(ecsPath, {
      field_path: ecsPath,
      field_type: inferEcsFieldType(ecsPath),
      is_required: critical.has(ecsPath),
      is_indexed: false,
      is_embeddable: false,
      description: "",
      source_path: sourcePath,
    });
  }

  const mergeRow = (pathKey: string, o: Record<string, unknown>) => {
    let row = byPath.get(pathKey);
    if (!row) {
      row = {
        field_path: pathKey,
        field_type: asStr(o.field_type || o.type, inferEcsFieldType(pathKey)),
        is_required: asBool(o.is_required, critical.has(pathKey)),
        is_indexed: asBool(o.is_indexed, false),
        is_embeddable: asBool(o.is_embeddable, false),
        description: asStr(o.description),
        source_path: asStr(o.source_path || o.source) || undefined,
      };
      byPath.set(pathKey, row);
      return;
    }
    row.field_type = asStr(o.field_type || o.type, row.field_type);
    row.is_required = asBool(o.is_required, row.is_required);
    row.is_indexed = asBool(o.is_indexed, row.is_indexed);
    row.is_embeddable = asBool(o.is_embeddable, row.is_embeddable);
    const desc = asStr(o.description);
    if (desc) row.description = desc;
    const sp = asStr(o.source_path || o.source);
    if (sp) row.source_path = sp;
  };

  for (const raw of doc.fields ?? []) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const o = raw as Record<string, unknown>;
    const pathExplicit = asStr(o.field_path || o.ecs_path);
    const sourcePath = asStr(o.source_path || o.source);

    if (pathExplicit) {
      mergeRow(pathExplicit, o);
      continue;
    }

    if (sourcePath) {
      const hit = [...byPath.entries()].find(([, r]) => r.source_path === sourcePath);
      if (hit) {
        mergeRow(hit[0], o);
        continue;
      }
    }

    const nameOnly = asStr(o.field_name || o.name, `extra_${byPath.size}`);
    const syntheticPath = nameOnly;
    mergeRow(syntheticPath, { ...o, field_path: syntheticPath });
  }

  return [...byPath.values()].sort((a, b) => a.field_path.localeCompare(b.field_path));
}
