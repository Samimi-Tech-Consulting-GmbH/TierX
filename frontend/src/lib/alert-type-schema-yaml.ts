import type { AlertTypeSchemaDocument } from "@/lib/types";

/** Suggest next patch (1.0.0 → 1.0.1). Falls back to `${current}-draft` if not semver-ish. */
export function suggestNextPatchVersion(current: string): string {
  const m = /^(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$/.exec(current.trim());
  if (!m) return `${current}-draft`;
  const patch = String(parseInt(m[3]!, 10) + 1);
  return `${m[1]}.${m[2]}.${patch}${m[4] ?? ""}${m[5] ?? ""}`;
}

function yamlScalar(s: string): string {
  if (s.includes("\n")) return JSON.stringify(s);
  if (/^[\d.:*@a-zA-Z0-9_/-]+$/.test(s) && !["true", "false", "null"].includes(s)) {
    return s;
  }
  return JSON.stringify(s);
}

function indentBlock(text: string, spaces: number): string {
  const pad = " ".repeat(spaces);
  return text
    .split("\n")
    .map((line) => (line ? pad + line : line))
    .join("\n");
}

/**
 * Rebuild YAML suitable for "Create new version" from a stored schema (new semver from options).
 */
export function buildAlertTypeSchemaYamlFromDocument(
  doc: AlertTypeSchemaDocument,
  options?: { version?: string },
): string {
  const version = options?.version ?? suggestNextPatchVersion(doc.version);
  const lines: string[] = [];

  lines.push(`# Cloned from version ${doc.version} (${doc.schema_id})`);
  lines.push(`alert_type: ${yamlScalar(doc.alert_type)}`);
  lines.push(`version: ${yamlScalar(version)}`);

  const desc = doc.description?.trim() ?? "";
  if (desc.includes("\n")) {
    lines.push("description: >");
    lines.push(indentBlock(desc, 2));
  } else if (desc) {
    lines.push(`description: ${yamlScalar(desc)}`);
  } else {
    lines.push(`description: ${yamlScalar("")}`);
  }

  if (doc.fields?.length) {
    lines.push("fields:");
    for (const raw of doc.fields) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
      lines.push("  -");
      for (const [k, v] of Object.entries(raw)) {
        if (v === null || v === undefined) continue;
        if (typeof v === "object") {
          lines.push(`    ${k}: ${JSON.stringify(v)}`);
        } else {
          lines.push(`    ${k}: ${yamlScalar(String(v))}`);
        }
      }
    }
  }

  lines.push("field_mapping:");
  const map = doc.field_mapping as Record<string, string>;
  for (const [k, v] of Object.entries(map || {})) {
    lines.push(`  ${k}: ${yamlScalar(v)}`);
  }

  lines.push("critical_fields:");
  for (const c of doc.critical_fields ?? []) {
    lines.push(`  - ${yamlScalar(c)}`);
  }

  if (doc.severity != null && doc.severity !== "") {
    lines.push(`severity: ${yamlScalar(String(doc.severity))}`);
  }

  return lines.join("\n") + "\n";
}

/**
 * Best-effort extraction of the top-level `alert_type:` value from a YAML document.
 * Returns the parsed scalar, or `null` if no top-level key was found. The backend
 * still performs full validation; this helper exists purely for client-side guardrails
 * (e.g. blocking a "Create new version" upload whose alert type does not match the source).
 */
export function extractAlertTypeFromYamlText(text: string): string | null {
  const lines = text.split(/\r?\n/);
  for (const raw of lines) {
    if (!raw || raw.startsWith("#")) continue;
    const m = /^alert_type\s*:\s*(.*)$/.exec(raw);
    if (!m) continue;
    let val = m[1] ?? "";
    if (!/^["']/.test(val)) {
      const hashIdx = val.indexOf("#");
      if (hashIdx >= 0) val = val.slice(0, hashIdx);
    }
    val = val.trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    return val.length > 0 ? val : null;
  }
  return null;
}
