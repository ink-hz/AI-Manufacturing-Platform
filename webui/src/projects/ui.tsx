import { useEffect, useRef, type ReactNode } from "react";
export type DirtyChange = (key: string, dirty: boolean) => void;
export function useDirty(key: string, dirty: boolean, onDirty: DirtyChange) {
  useEffect(() => {
    onDirty(key, dirty);
    return () => onDirty(key, false);
  }, [key, dirty, onDirty]);
}
export function Dialog({
  children,
  onClose,
  label = "尚未保存的更改",
}: {
  children: ReactNode;
  onClose: () => void;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const box = ref.current;
    box?.querySelector<HTMLElement>("button,input")?.focus();
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
      if (e.key === "Tab" && box) {
        const nodes = [
          ...box.querySelectorAll<HTMLElement>(
            'button:not(:disabled),input:not(:disabled),[tabindex="0"]',
          ),
        ];
        const i = nodes.indexOf(document.activeElement as HTMLElement);
        if (e.shiftKey && i <= 0) {
          e.preventDefault();
          nodes.at(-1)?.focus();
        } else if (!e.shiftKey && i === nodes.length - 1) {
          e.preventDefault();
          nodes[0]?.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="mf-dialog-backdrop">
      <div
        className="mf-dialog"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={label}
      >
        {children}
      </div>
    </div>
  );
}
export function SaveError({
  error,
  onReload,
  onKeep,
}: {
  error: string;
  onReload?: () => void;
  onKeep?: () => void;
}) {
  return (
    <div role="alert" className="mf-error">
      {error}。尚未保存，草稿已保留。
      {error.includes("内容已更新") && (
        <div className="mf-actions">
          <button type="button" onClick={onKeep}>
            保留草稿
          </button>
          {onReload && (
            <button type="button" onClick={onReload}>
              放弃草稿并重新读取
            </button>
          )}
        </div>
      )}
    </div>
  );
}
export function ReadError({
  error,
  onRetry,
  retained = false,
  disabled = false,
}: {
  error: string;
  onRetry: () => void;
  retained?: boolean;
  disabled?: boolean;
}) {
  return (
    <div role="alert" className="mf-error">
      读取失败。{error}。{retained ? "保留上次读取内容。" : ""}
      <button type="button" disabled={disabled} onClick={onRetry}>
        重试读取项目
      </button>
    </div>
  );
}
export function Status({ value, text }: { value: string; text: string }) {
  return <span className={`mf-status mf-status-${value}`}>{text}</span>;
}
export function Choice({
  label,
  value,
  values,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  values: Record<string, string>;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="mf-field">
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {Object.entries(values).map(([id, name]) => (
          <option key={id} value={id}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}
