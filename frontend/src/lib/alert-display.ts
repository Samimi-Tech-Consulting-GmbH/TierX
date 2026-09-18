export const HOST_KEY = "host.hostname";

export interface SeverityDisplay {
  label: string;
  className: string;
}

const UNKNOWN_SEVERITY: SeverityDisplay = {
  label: "—",
  className: "text-muted-foreground",
};

export function severityOf(alert: {
  severity?: unknown;
}): SeverityDisplay {
  return severityFromValue(alert.severity);
}

export function severityFromValue(raw: unknown): SeverityDisplay {
  if (raw == null) return UNKNOWN_SEVERITY;

  const value = String(raw).trim().toLowerCase();
  if (value === "5" || value === "critical" || value === "kritisch")
    return { label: "Critical", className: "text-[#dc2626]" };
  if (value === "4" || value === "high")
    return { label: "High", className: "text-[#d97706]" };
  if (value === "3" || value === "medium")
    return { label: "Medium", className: "text-[#eab308]" };
  if (value === "2" || value === "1" || value === "low")
    return { label: "Low", className: "text-[#2563eb]" };
  return UNKNOWN_SEVERITY;
}

export function isCriticalSeverity(raw: unknown): boolean {
  return severityFromValue(raw).label === "Critical";
}

export function statusTone(status: string | null | undefined): string {
  switch (status) {
    case "ANALYZED":
      return "bg-[#16a34a]";
    case "ESCALATED":
      return "bg-[#d97706]";
    case "ERROR":
      return "bg-destructive";
    case "ANALYZING":
      return "bg-[#2563eb]";
    default:
      return "bg-[#525252]";
  }
}

export function alertTypeLabel(alertType: string | null | undefined): string {
  const segment = alertType?.split(".").pop();
  if (!segment) return "—";
  return segment
    .split(/[_-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export const TIME_RANGES = [
  { value: "all", label: "All time", hours: undefined },
  { value: "24", label: "Last 24 hours", hours: 24 },
  { value: "168", label: "Last 7 days", hours: 168 },
  { value: "720", label: "Last 30 days", hours: 720 },
] as const;

export const TIME_RANGE_ITEMS = TIME_RANGES.map(({ value, label }) => ({
  value,
  label,
}));
