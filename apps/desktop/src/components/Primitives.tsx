import type { CSSProperties, ReactNode } from "react";

export function Panel({
  children, className = "", style,
}: { children: ReactNode; className?: string; style?: CSSProperties }) {
  return <div className={`panel ${className}`} style={style}>{children}</div>;
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="eyebrow">{children}</div>;
}

export function Health({ status, label }: { status: string; label: string }) {
  const tone =
    ({ READY: "ready", PARTIAL: "warn", REQUIRES_FREEZE: "warn", BLOCKED: "bad" } as
      Record<string, string>)[status] ?? "unknown";
  return (
    <span className={`health ${tone}`}>
      <span className="dot" />
      {label}
    </span>
  );
}

export function Notice({
  children, tone = "",
}: { children: ReactNode; tone?: "" | "bad" | "warn" }) {
  return <div className={`notice ${tone}`}>{children}</div>;
}

export function Advanced({ title = "Advanced", children }: { title?: string; children: ReactNode }) {
  return (
    <details className="advanced">
      <summary>{title}</summary>
      <div className="advanced-body">{children}</div>
    </details>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <div className="big">{title}</div>
      {hint && <div>{hint}</div>}
    </div>
  );
}

export function Tile({
  on, onClick, label, sub,
}: { on: boolean; onClick: () => void; label: string; sub?: string }) {
  return (
    <button className={`tile ${on ? "on" : ""}`} onClick={onClick} type="button">
      {label}
      {sub && <span className="sub">{sub}</span>}
    </button>
  );
}

export function Check({
  on, onClick, label, why, disabled = false,
}: {
  on: boolean; onClick: () => void; label: string; why?: string; disabled?: boolean;
}) {
  return (
    <button
      className={`check ${on && !disabled ? "on" : ""}`}
      onClick={onClick}
      disabled={disabled}
      type="button"
    >
      <span className="box">{on && !disabled ? "✓" : ""}</span>
      <span>{label}</span>
      {why && <span className="why">{why}</span>}
    </button>
  );
}
