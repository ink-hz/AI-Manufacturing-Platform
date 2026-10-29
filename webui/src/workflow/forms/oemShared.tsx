import { useEffect, useRef, useState } from "react";
import type {
  ObjectKind,
  ObjectSummary,
  ObjectDetail,
  WorkspaceProps,
  OEMCommands,
  PublicAssetEntry,
} from "../types";
import { Field, ObjectChoice } from "./shared";
export interface OEMFormProps extends WorkspaceProps {
  action: OEMCommands["action"];
  items: Partial<Record<ObjectKind, ObjectSummary[]>>;
  configurationAdmin?: boolean;
  initialObject?: ObjectDetail | null;
  publicAssets?: PublicAssetEntry[];
}
export const decisions = {
  pass: "通过",
  blocked: "阻断",
  not_applicable: "不适用（需依据）",
};
export const origins = { manual: "人工登记的实际观察", demo: "隔离模拟证据" };
export const selected = (p: OEMFormProps, kind: ObjectKind) =>
  p.initialObject?.value.kind === kind ? p.initialObject.summary.id : "";
export function Toggle({
  name,
  value,
  onChange,
}: {
  name: string;
  value: boolean;
  onChange(v: boolean): void;
}) {
  return (
    <label>
      <input
        type="checkbox"
        aria-label={name}
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />
      {name}
    </label>
  );
}
export function ManyObjects({
  name,
  items,
  value,
  onChange,
}: {
  name: string;
  items: ObjectSummary[];
  value: string[];
  onChange(v: string[]): void;
}) {
  return (
    <fieldset>
      <legend>{name}</legend>
      {items.length ? (
        items.map((item) => (
          <Toggle
            key={item.id}
            name={`${name} · ${item.title}`}
            value={value.includes(item.id)}
            onChange={(checked) =>
              onChange(
                checked
                  ? [...value, item.id]
                  : value.filter((id) => id !== item.id),
              )
            }
          />
        ))
      ) : (
        <p>暂无可选记录；请先登记或读取更多。</p>
      )}
    </fieldset>
  );
}
export function Names({
  name,
  value,
  onChange,
  max = 100,
}: {
  name: string;
  value: string[];
  onChange(v: string[]): void;
  max?: number;
}) {
  return (
    <fieldset>
      <legend>{name}</legend>
      {value.map((text, i) => (
        <div key={i}>
          <Field
            name={`${name} ${i + 1}`}
            value={text}
            onChange={(v) => onChange(value.map((x, n) => (n === i ? v : x)))}
          />
          <button
            type="button"
            disabled={value.length === 1}
            onClick={() => onChange(value.filter((_, n) => n !== i))}
          >
            移除{name} {i + 1}
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={value.length >= max}
        onClick={() => onChange([...value, ""])}
      >
        添加{name}
      </button>
    </fieldset>
  );
}
export function Pick({
  p,
  kind,
  name,
  value,
  onChange,
  required = true,
  items,
}: {
  p: OEMFormProps;
  kind: ObjectKind;
  name: string;
  value: string | null;
  onChange(v: string): void;
  required?: boolean;
  items?: ObjectSummary[];
}) {
  return (
    <ObjectChoice
      name={name}
      value={value || ""}
      onChange={onChange}
      required={required}
      items={items || p.items[kind] || []}
    />
  );
}
// Selection reads are bound to the current project, value and component lifetime.
export function useSelected(p: WorkspaceProps) {
  const [detail, setDetail] = useState<ObjectDetail | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  useEffect(
    () => () => {
      generation.current++;
      request.current?.abort();
    },
    [p.api, p.project.id],
  );
  const read = async (
    kind: ObjectKind,
    id: string,
    apply?: (d: ObjectDetail) => void,
  ) => {
    request.current?.abort();
    const current = ++generation.current;
    const c = new AbortController();
    request.current = c;
    setDetail(null);
    setError("");
    setLoading(!!id);
    if (!id) return;
    try {
      const d = await p.api.object(p.project.id, kind, id, c.signal);
      if (current === generation.current && !c.signal.aborted) {
        setDetail(d);
        apply?.(d);
      }
    } catch (e) {
      if (current === generation.current && !c.signal.aborted)
        setError(String(e));
    } finally {
      if (current === generation.current) setLoading(false);
    }
  };
  return {
    detail,
    read,
    loading,
    error,
    notice: (
      <>
        {loading && <p role="status">正在读取所选记录…</p>}
        {error && <p role="alert">{error}</p>}
      </>
    ),
  };
}
