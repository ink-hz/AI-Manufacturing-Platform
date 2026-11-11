import { useId, type ReactNode } from "react";

export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className="pt-badge" data-tone={tone}>{children}</span>;
}

export function Metric({ label, value, detail, tone = "neutral", onClick }: {
  label: string;
  value: string | null;
  detail?: ReactNode;
  tone?: Tone;
  onClick?: () => void;
}) {
  const content = <><span className="pt-metric-label">{label}</span>{" "}<strong className="pt-metric-value">{value ?? "—"}</strong>{detail != null && <span className="pt-metric-detail">{detail}</span>}</>;
  const visualTone = value == null || (value === "0" && tone === "danger") ? "neutral" : tone;
  return onClick
    ? <button type="button" className="pt-metric pt-metric-action" data-tone={visualTone} onClick={onClick}>{content}</button>
    : <div role="group" aria-label={label} className="pt-metric" data-tone={visualTone}>{content}</div>;
}

export function Panel({ title, eyebrow, description, actions, children, className = "" }: {
  title: ReactNode;
  eyebrow?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const titleId = useId();
  return <section className={`pt-panel ${className}`} aria-labelledby={titleId}>
    <header className="pt-section-heading"><div>{eyebrow && <p className="pt-eyebrow">{eyebrow}</p>}<h3 id={titleId}>{title}</h3>{description && <p className="pt-section-description">{description}</p>}</div>{actions && <div className="pt-actions">{actions}</div>}</header>
    <div className="pt-panel-body">{children}</div>
  </section>;
}

export function ResultBadge({ value }: { value: unknown }) {
  if (value === "1" || value === 1) return <Badge tone="success">通过 PASS</Badge>;
  if (value === "2" || value === 2) return <Badge tone="danger">失败 FAIL</Badge>;
  const raw = typeof value === "string" || typeof value === "number" ? String(value) : "";
  return <Badge>结果未知{raw ? `（${raw}）` : ""}</Badge>;
}

export function EmptyState({ title, description }: { title: ReactNode; description?: ReactNode }) {
  return <div className="pt-empty"><strong>{title}</strong>{description && <p>{description}</p>}</div>;
}

/** Only convert the bounded, fixed-point ratio to Number; source counts stay exact. */
export function boundedPercent(value: string, max: string): number {
  if (!/^\d+$/.test(value) || !/^\d+$/.test(max)) throw new RangeError("Counts must be nonnegative decimal integers");
  const count = BigInt(value), total = BigInt(max);
  if (total === 0n) return 0;
  if (count >= total) return 100;
  return Number(count * 10000n / total) / 100;
}
