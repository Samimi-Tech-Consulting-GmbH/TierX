/** Locale-formatted date/time for admin tables and detail views. */
export function formatLocaleDateTime(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString();
}

export function timeAgo(date: Date, now: Date = new Date()): string {
  const seconds = Math.max(
    Math.round((now.getTime() - date.getTime()) / 1000),
    0,
  );
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 60],
    ["minute", 60],
    ["hour", 24],
    ["day", 7],
    ["week", 4.35],
    ["month", 12],
  ];

  let value = seconds;
  for (const [unit, step] of units) {
    if (value < step) {
      return new Intl.RelativeTimeFormat("en-US", { numeric: "auto" }).format(
        -Math.round(value),
        unit,
      );
    }
    value /= step;
  }
  return new Intl.RelativeTimeFormat("en-US", { numeric: "auto" }).format(
    -Math.round(value),
    "year",
  );
}

export function formatShortDateTime(v: string | null | undefined): string {
  if (v == null || v === "") return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
