/** Presentation helpers. No business logic lives here. */

export function bytes(n: number): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function clock(seconds: number | null | undefined): string {
  if (seconds == null || !isFinite(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function bars(n: number): string {
  const rounded = Math.round(n * 10) / 10;
  return Number.isInteger(rounded) ? `${rounded}` : rounded.toFixed(1);
}

export function tempo(bpm: number | null): string {
  return bpm == null ? "—" : `${Math.round(bpm * 10) / 10}`;
}

export function when(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export const healthClass = (status: string): string =>
  ({
    READY: "ready", PARTIAL: "warn", REQUIRES_FREEZE: "warn",
    BLOCKED: "bad", UNKNOWN: "unknown",
  } as Record<string, string>)[status] ?? "unknown";

export const DRUM_ROLES = new Set(["kick", "snare", "hats", "perc"]);
