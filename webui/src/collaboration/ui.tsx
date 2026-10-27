import { useEffect, useRef, useState, type ReactNode } from "react";
import { message } from "../projects/types";
import { useDirty, type DirtyChange } from "../projects/ui";
import type { Operation } from "./types";
export function Field({
  label,
  value,
  onChange,
  type = "text",
  required = false,
  maxLength = 2000,
}: {
  label: string;
  value: string | null;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  maxLength?: number;
}) {
  return (
    <label className="mf-field">
      {label}
      {required ? " *" : ""}
      <input
        aria-label={label}
        type={type}
        maxLength={maxLength}
        required={required}
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
export function Note({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="mf-field mf-full-width">
      {label}
      <textarea
        aria-label={label}
        rows={3}
        maxLength={6000}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
export function Evidence({ value }: { value: string | null | undefined }) {
  const safe =
    !!value &&
    /^https?:\/\//i.test(value) &&
    (() => {
      try {
        return ["http:", "https:"].includes(new URL(value).protocol);
      } catch {
        return false;
      }
    })();
  return safe ? (
    <a href={value!} target="_blank" rel="noopener noreferrer">
      {value}
    </a>
  ) : (
    <span>{value || "未登记"}</span>
  );
}
export interface EditorHost {
  readOnly: boolean;
  onDirty: DirtyChange;
  onSaved: () => Promise<void>;
  onCancel: () => void;
  requestLeave?: (f: () => void) => void;
  onReload?: () => void;
}
export function MutationForm<T extends object>({
  draft,
  initial,
  version,
  write,
  children,
  label,
  onSaved,
  onCancel,
  onDirty,
  readOnly,
  changed = false,
  requestLeave,
  dirtyKey = "control-editor",
  onReload,
}: {
  draft: T;
  initial: T;
  version?: number;
  write: (body: T & Operation) => Promise<unknown>;
  children: ReactNode;
  label: string;
  changed?: boolean;
  dirtyKey?: string;
} & EditorHost) {
  // A live collection refresh cannot advance the CAS of retained draft content.
  // Explicit guarded discard remounts the form with a new draft baseline.
  const [baselineVersion] = useState(version);
  const [busy, setBusy] = useState(false),
    [frozen, setFrozen] = useState(false),
    [committed, setCommitted] = useState(false),
    [error, setError] = useState("");
  const active = useRef(true),
    lock = useRef(false),
    receipt = useRef<(T & Operation) | null>(null),
    committedRef = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useDirty(
    dirtyKey,
    !committed &&
      (changed ||
        JSON.stringify(draft) !== JSON.stringify(initial) ||
        frozen ||
        busy),
    onDirty,
  );
  async function run() {
    if (lock.current || readOnly) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      if (!committedRef.current) {
        receipt.current ??= JSON.parse(
          JSON.stringify({
            ...draft,
            operation_id: crypto.randomUUID(),
            ...(baselineVersion ? { expected_version: baselineVersion } : {}),
          }),
        );
        setFrozen(true);
        await write(receipt.current!);
        committedRef.current = true;
        if (active.current) setCommitted(true);
      }
      if (active.current) {
        await onSaved();
        if (active.current) onCancel();
      }
    } catch (e) {
      if (active.current) setError(message(e));
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <form
      className="mf-editor mf-control-editor"
      onSubmit={(e) => {
        e.preventDefault();
        void run();
      }}
    >
      {committed ? (
        <>
          <p role="status">已保存。刷新失败时仅重新读取，不会重复提交。</p>
          {error && (
            <p role="alert" className="mf-error">
              {error}
            </p>
          )}
          <button type="button" disabled={busy} onClick={() => void run()}>
            重新读取已保存结果
          </button>
          <button type="button" disabled={busy} onClick={onCancel}>
            关闭已保存记录
          </button>
        </>
      ) : (
        <>
          <fieldset
            className="mf-form-grid"
            disabled={busy || frozen || readOnly}
          >
            {children}
          </fieldset>
          {error && (
            <p role="alert" className="mf-error">
              {error}。草稿已保留。
              {onReload && error.includes("内容已更新") && (
                <button type="button" disabled={busy} onClick={onReload}>
                  放弃草稿并重新读取
                </button>
              )}
            </p>
          )}
          {frozen && (
            <p className="mf-muted">
              本次请求已锁定，重试沿用原内容和操作标识。修改前请明确重置。
            </p>
          )}
          <div className="mf-actions">
            {!readOnly && (
              <button className="mf-primary" type="submit" disabled={busy}>
                {busy ? "正在保存…" : label}
              </button>
            )}
            {frozen && (
              <button
                type="button"
                disabled={busy || readOnly}
                onClick={() => {
                  receipt.current = null;
                  setFrozen(false);
                  setError("");
                }}
              >
                重置本次请求并继续编辑
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                requestLeave ? requestLeave(onCancel) : onCancel()
              }
            >
              返回列表
            </button>
          </div>
        </>
      )}
    </form>
  );
}
export function useCollection<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState("");
  const sequence = useRef(0),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      sequence.current++;
    };
  }, []);
  async function refresh() {
    const seq = ++sequence.current;
    setError("");
    try {
      const result = await load();
      if (alive.current && seq === sequence.current) setData(result);
    } catch (e) {
      if (alive.current && seq === sequence.current) setError(message(e));
      throw e;
    }
  }
  return { data, error, refresh };
}
export function ReadState({
  error,
  retry,
}: {
  error: string;
  retry: () => void;
}) {
  return error ? (
    <div role="alert" className="mf-error">
      读取失败。{error}
      <button onClick={retry}>重试读取</button>
    </div>
  ) : null;
}
