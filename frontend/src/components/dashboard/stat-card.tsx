import { cn } from "@/lib/utils";

/** Metric tile used across the dashboard headers (playbooks, debug, …). */
export function StatCard({
  label,
  value,
  hint,
  icon,
  iconClass,
}: {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  iconClass: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg bg-card px-6 py-5">
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-bold text-foreground">{value}</p>
        <p className="mt-1 text-xs text-[#737373]">{hint}</p>
      </div>
      <span
        className={cn(
          "flex size-11 shrink-0 items-center justify-center rounded-full",
          iconClass,
        )}
      >
        {icon}
      </span>
    </div>
  );
}
