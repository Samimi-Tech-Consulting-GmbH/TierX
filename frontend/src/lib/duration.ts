function compactNumber(value: number, fractionDigits: number): string {
  return value.toFixed(fractionDigits).replace(/\.0+$/, "");
}

function millisecondsLabel(milliseconds: number): string {
  const rounded = Math.round(milliseconds * 1_000) / 1_000;
  return `${rounded} ms`;
}

export function formatDurationMs(milliseconds: number): string {
  if (!Number.isFinite(milliseconds)) return "—";

  const safeMilliseconds = Math.max(0, milliseconds);
  const raw = millisecondsLabel(safeMilliseconds);

  if (safeMilliseconds > 90_000) {
    return `${raw} (${compactNumber(safeMilliseconds / 60_000, 1)} min)`;
  }
  if (safeMilliseconds > 500) {
    return `${raw} (${compactNumber(safeMilliseconds / 1_000, 1)} s)`;
  }
  return raw;
}
