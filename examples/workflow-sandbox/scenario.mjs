// Portable scenario contracts shared by the browser and local server.
export const PRESETS = [
  "independent",
  "correlated",
  "duplicates",
  "validation-failure",
];
const forbidden =
  /^(authorization|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|credentials?|database[_-]?url|mongo[_-]?url|entry[_-]?token)$/i;
const blockedPaths = new Set(["__proto__", "prototype", "constructor"]);
export const clone = (value) => JSON.parse(JSON.stringify(value));
export function safeData(value, depth = 0) {
  if (depth > 32) throw new Error("JSON nesting exceeds 32 levels.");
  if (
    typeof value === "string" &&
    (/-----BEGIN .*PRIVATE KEY-----/.test(value) ||
      /(?:Bearer\s+[A-Za-z0-9._-]{12,}|eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|(?:mongodb(?:\+srv)?|postgres(?:ql)?):\/\/[^\s]*@)/i.test(
        value,
      ))
  )
    throw new Error("Remove credentials/private keys from synthetic data.");
  if (Array.isArray(value)) value.forEach((item) => safeData(item, depth + 1));
  else if (value && typeof value === "object")
    for (const [key, child] of Object.entries(value)) {
      if (forbidden.test(key) || blockedPaths.has(key))
        throw new Error(
          "Credential and unsafe property names are not allowed in scenarios.",
        );
      safeData(child, depth + 1);
    }
  return value;
}
export function object(value) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Each alert must be one JSON object.");
  if (new TextEncoder().encode(JSON.stringify(value)).length > 256 * 1024)
    throw new Error("Alert exceeds 256 KiB.");
  return safeData(value);
}
export function pathParts(path) {
  const parts = path.split(".");
  if (
    !path ||
    path.length > 256 ||
    parts.some((key) => !/^[A-Za-z0-9_@-]+$/.test(key) || blockedPaths.has(key))
  )
    throw new Error("Use safe dotted field paths, such as result._time.");
  return parts;
}
export function readPath(value, path) {
  return pathParts(path).reduce((item, key) => item?.[key], value);
}
export function writePath(value, path, next, remove = false) {
  const parts = pathParts(path),
    last = parts.pop();
  let parent = value;
  for (const key of parts) {
    if (
      !parent[key] ||
      typeof parent[key] !== "object" ||
      Array.isArray(parent[key])
    )
      parent[key] = {};
    parent = parent[key];
  }
  if (remove) delete parent[last];
  else parent[last] = next;
}
const keywords = new Set([
  "type",
  "properties",
  "required",
  "additionalProperties",
  "items",
  "minItems",
  "maxItems",
  "minLength",
  "maxLength",
  "minimum",
  "maximum",
  "enum",
  "const",
  "description",
  "title",
  "$schema",
  "allOf",
  "anyOf",
  "oneOf",
]);
export function checkSchema(schema, depth = 0) {
  if (typeof schema === "boolean") return;
  if (
    !schema ||
    typeof schema !== "object" ||
    Array.isArray(schema) ||
    depth > 24
  )
    throw new Error("Invalid or excessively nested JSON Schema.");
  for (const key of Object.keys(schema))
    if (!keywords.has(key))
      throw new Error(
        `Unsupported JSON Schema keyword: ${key}. See README for the supported subset.`,
      );
  const types = [
    "object",
    "array",
    "string",
    "number",
    "integer",
    "boolean",
    "null",
  ];
  if (
    schema.type !== undefined &&
    (!(Array.isArray(schema.type) ? schema.type : [schema.type]).length ||
      !(Array.isArray(schema.type) ? schema.type : [schema.type]).every(
        (type) => types.includes(type),
      ))
  )
    throw new Error("Invalid schema type.");
  if (
    schema.required !== undefined &&
    (!Array.isArray(schema.required) ||
      schema.required.some((key) => typeof key !== "string"))
  )
    throw new Error("Schema required must be a string array.");
  if (schema.properties !== undefined) {
    if (
      !schema.properties ||
      typeof schema.properties !== "object" ||
      Array.isArray(schema.properties)
    )
      throw new Error("Invalid schema properties.");
    for (const child of Object.values(schema.properties))
      checkSchema(child, depth + 1);
  }
  for (const key of ["items", "additionalProperties"])
    if (schema[key] !== undefined) checkSchema(schema[key], depth + 1);
  for (const key of ["allOf", "anyOf", "oneOf"])
    if (schema[key] !== undefined) {
      if (!Array.isArray(schema[key]) || !schema[key].length)
        throw new Error("Invalid schema alternatives.");
      schema[key].forEach((child) => checkSchema(child, depth + 1));
    }
  for (const key of [
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
  ])
    if (
      schema[key] !== undefined &&
      (typeof schema[key] !== "number" || !Number.isFinite(schema[key]))
    )
      throw new Error("Invalid schema bound.");
  for (const key of ["minItems", "maxItems", "minLength", "maxLength"])
    if (
      schema[key] !== undefined &&
      (!Number.isInteger(schema[key]) || schema[key] < 0)
    )
      throw new Error("Schema lengths must be non-negative integers.");
  if (
    schema.enum !== undefined &&
    (!Array.isArray(schema.enum) || !schema.enum.length)
  )
    throw new Error("Invalid schema enum.");
}
const stable = (value) =>
  Array.isArray(value)
    ? value.map(stable)
    : value && typeof value === "object"
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, stable(value[key])]),
        )
      : value;
const equal = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));
export function validateSchema(value, schema, path = "$") {
  if (schema === true) return;
  if (schema === false) throw new Error(`${path}: prohibited by schema.`);
  const matches = (type) =>
    type === "null"
      ? value === null
      : type === "array"
        ? Array.isArray(value)
        : type === "object"
          ? value !== null && typeof value === "object" && !Array.isArray(value)
          : type === "integer"
            ? Number.isInteger(value)
            : typeof value === type;
  if (
    schema.type !== undefined &&
    !(Array.isArray(schema.type) ? schema.type : [schema.type]).some(matches)
  )
    throw new Error(`${path}: incorrect type.`);
  if (
    (schema.enum && !schema.enum.some((item) => equal(item, value))) ||
    ("const" in schema && !equal(schema.const, value))
  )
    throw new Error(`${path}: value not allowed.`);
  for (const key of ["allOf", "anyOf", "oneOf"])
    if (schema[key]) {
      const passed = schema[key].filter((child) => {
        try {
          validateSchema(value, child, path);
          return true;
        } catch {
          return false;
        }
      }).length;
      if (
        (key === "allOf" && passed !== schema[key].length) ||
        (key === "anyOf" && !passed) ||
        (key === "oneOf" && passed !== 1)
      )
        throw new Error(`${path}: schema alternatives failed.`);
    }
  if (matches("object")) {
    for (const key of schema.required || [])
      if (!Object.hasOwn(value, key))
        throw new Error(`${path}.${key}: required field missing.`);
    for (const [key, item] of Object.entries(value)) {
      if (Object.hasOwn(schema.properties || {}, key))
        validateSchema(item, schema.properties[key], `${path}.${key}`);
      else if (schema.additionalProperties !== undefined)
        validateSchema(item, schema.additionalProperties, `${path}.${key}`);
    }
  }
  if (Array.isArray(value)) {
    if (
      value.length < (schema.minItems ?? 0) ||
      value.length > (schema.maxItems ?? Infinity)
    )
      throw new Error(`${path}: array length invalid.`);
    if (schema.items !== undefined)
      value.forEach((item, index) =>
        validateSchema(item, schema.items, `${path}[${index}]`),
      );
  }
  if (
    typeof value === "string" &&
    ([...value].length < (schema.minLength ?? 0) ||
      [...value].length > (schema.maxLength ?? Infinity))
  )
    throw new Error(`${path}: string length invalid.`);
  if (
    typeof value === "number" &&
    (value < (schema.minimum ?? -Infinity) ||
      value > (schema.maximum ?? Infinity))
  )
    throw new Error(`${path}: number outside bounds.`);
}
export function generationInput(body) {
  const sample = clone(object(body.sample));
  const description = String(body.description || "").trim();
  if (!description || description.length > 4000)
    throw new Error("Describe a synthetic scenario in 1–4000 characters.");
  safeData(description);
  const count = Number(body.count ?? 10),
    preset = body.preset || "independent";
  if (!Number.isInteger(count) || count < 1 || count > 20)
    throw new Error("Generate 1–20 alerts per batch.");
  if (!PRESETS.includes(preset)) throw new Error("Unknown scenario preset.");
  const negative = preset === "validation-failure";
  if (negative && body.negative !== true)
    throw new Error("Confirm intentional validation failure.");
  const missingPath = String(body.missing_path || "result.host");
  pathParts(missingPath);
  const schema = body.schema ?? null;
  if (schema !== null) {
    if (JSON.stringify(schema).length > 65536)
      throw new Error("Schema exceeds 64 KiB.");
    checkSchema(schema);
    validateSchema(sample, schema);
  }
  return {
    sample,
    description,
    count,
    preset,
    negative,
    missing_path: missingPath,
    schema,
  };
}
export function validateAlerts(alerts, schema = null, negative = false) {
  if (!Array.isArray(alerts) || !alerts.length || alerts.length > 1000)
    throw new Error("Scenario requires 1–1000 alert objects.");
  alerts.forEach((alert) => {
    object(alert);
    if (schema !== null && !negative) validateSchema(alert, schema);
  });
  return alerts;
}
export function replay(payload, settings, identity, timestamp) {
  const result = clone(payload);
  if (settings.refresh) {
    for (const path of settings.timestamp_paths)
      writePath(result, path, timestamp);
    for (const path of settings.unique_paths)
      writePath(result, path, `sandbox-${identity}`);
  }
  return result;
}
export function scenarioFile(body) {
  const settings = body.settings || {},
    schema = body.schema ?? null;
  if (schema !== null) checkSchema(schema);
  const preset = PRESETS.includes(body.preset) ? body.preset : "independent",
    negative = preset === "validation-failure" && body.negative === true;
  if (preset === "validation-failure" && !negative)
    throw new Error("Confirm intentional validation failure.");
  const paths = (key) => {
    const values =
      settings[key] ??
      (key === "timestamp_paths" ? ["result._time"] : ["result.rule_id"]);
    if (!Array.isArray(values) || values.length > 10)
      throw new Error("At most ten replay field paths.");
    values.forEach(pathParts);
    return values;
  };
  const interval = Number(settings.interval_seconds ?? 5),
    total = Number(settings.total ?? 10),
    duration = Number(settings.duration_minutes ?? 60);
  if (
    !Number.isFinite(interval) ||
    interval < 0.1 ||
    interval > 3600 ||
    !Number.isInteger(total) ||
    total < 1 ||
    total > 1000 ||
    !Number.isFinite(duration) ||
    duration < 0.01 ||
    duration > 60
  )
    throw new Error(
      "Run limits: 1–1000 alerts, 0.1–3600 seconds between sends, maximum 60 minutes.",
    );
  const result = {
    format_version: "1.0",
    name: String(body.name || "Synthetic scenario").slice(0, 160),
    description: String(body.description || "").slice(0, 4000),
    preset,
    negative,
    schema,
    missing_path: String(body.missing_path || "result.host"),
    alerts: clone(validateAlerts(body.alerts, schema, negative)),
    settings: {
      interval_seconds: interval,
      total,
      duration_minutes: duration,
      refresh: preset === "duplicates" ? false : settings.refresh === true,
      timestamp_paths: paths("timestamp_paths"),
      unique_paths: paths("unique_paths"),
    },
    generation: body.generation
      ? {
          provider: String(body.generation.provider || "imported").slice(0, 64),
          model: String(body.generation.model || "").slice(0, 128),
          generated_at: String(body.generation.generated_at || "").slice(0, 64),
          validation:
            schema === null
              ? "STRUCTURAL_ONLY"
              : negative
                ? "INTENTIONAL_NEGATIVE"
                : "SCHEMA_VALIDATED",
        }
      : null,
  };
  safeData(result);
  pathParts(result.missing_path);
  return result;
}
