import { Badge } from "@/components/ui/badge";
import { TenantStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const statusConfig: Record<
  TenantStatus,
  { label: string; className: string }
> = {
  [TenantStatus.ONBOARDING]: {
    label: "Onboarding",
    className:
      "bg-muted text-muted-foreground hover:bg-muted dark:bg-muted/80 dark:text-muted-foreground",
  },
  [TenantStatus.ACTIVE]: {
    label: "Active",
    className:
      "bg-green-100 text-green-800 hover:bg-green-100 dark:bg-green-900 dark:text-green-300",
  },
  [TenantStatus.SUSPENDED]: {
    label: "Suspended",
    className:
      "bg-amber-100 text-amber-800 hover:bg-amber-100 dark:bg-amber-900 dark:text-amber-300",
  },
  [TenantStatus.DELETED]: {
    label: "Deleted",
    className:
      "bg-red-100 text-red-800 hover:bg-red-100 dark:bg-red-900 dark:text-red-300",
  },
};

export function StatusBadge({ status }: { status: TenantStatus }) {
  const config = statusConfig[status];
  return (
    <Badge variant="secondary" className={cn("font-medium", config.className)}>
      {config.label}
    </Badge>
  );
}
