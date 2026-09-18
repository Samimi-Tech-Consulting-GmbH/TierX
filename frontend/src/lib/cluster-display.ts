export const CLUSTER_STATUSES = [
  "OPEN",
  "UNDER_INVESTIGATION",
  "ESCALATED",
  "CLOSED",
  "FALSE_POSITIVE",
] as const;

export const CLUSTER_STATUS_ITEMS = [
  { value: "ALL", label: "All statuses" },
  ...CLUSTER_STATUSES.map((s) => ({ value: s, label: titleCase(s) })),
];

export function clusterStatusTone(status: string | null | undefined): string {
  switch (status) {
    case "OPEN":
      return "bg-[#2563eb]";
    case "UNDER_INVESTIGATION":
      return "bg-[#eab308]";
    case "ESCALATED":
      return "bg-[#d97706]";
    case "CLOSED":
      return "bg-[#16a34a]";
    case "FALSE_POSITIVE":
      return "bg-[#525252]";
    default:
      return "bg-[#525252]";
  }
}

export function titleCase(value: string): string {
  return value
    .split(/[_-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(" ");
}

export function analysisStatusTone(status: string | null | undefined): string {
  switch (status) {
    case "SUCCEEDED":
    case "COMPLETED":
      return "text-[#16a34a]";
    case "FAILED":
      return "text-[#dc2626]";
    case "IN_PROGRESS":
    case "RUNNING":
    case "REQUESTED":
      return "text-[#2563eb]";
    default:
      return "text-muted-foreground";
  }
}

export function runStateTone(state: string | null | undefined): string {
  switch (state) {
    case "SUCCEEDED":
      return "bg-[#16a34a]";
    case "FAILED":
      return "bg-destructive";
    case "RUNNING":
      return "bg-[#2563eb]";
    case "PENDING":
      return "bg-[#d97706]";
    default:
      return "bg-[#525252]";
  }
}

export const PANEL = "rounded-lg bg-card p-6";
export const PANEL_TITLE =
  "flex items-center gap-2 text-base font-bold text-foreground";
export const PANEL_NOTE = "mt-1 text-sm text-muted-foreground";
export const TABLE_HEAD =
  "bg-[#171717] text-xs font-bold text-muted-foreground";
export const TABLE_ROW = "border-t border-white/5";
export const PILL =
  "inline-flex whitespace-nowrap rounded-full px-3 py-1 text-xs font-bold text-white";

export function confidenceTone(confidence: string | null | undefined): string {
  switch (confidence) {
    case "HIGH":
      return "bg-[#16a34a]";
    case "MEDIUM":
      return "bg-[#d97706]";
    case "LOW":
      return "bg-destructive";
    default:
      return "bg-[#525252]";
  }
}
