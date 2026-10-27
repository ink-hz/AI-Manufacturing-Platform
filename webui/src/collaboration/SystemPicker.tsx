import { createContext, useContext } from "react";
import type { Api } from "../api";
import { Choice } from "../projects/ui";
import { useCollection } from "./ui";
export const LineScope = createContext("");
export function SystemPicker({
  api,
  label,
  value,
  onChange,
}: {
  api: Api;
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const lineId = useContext(LineScope),
    c = useCollection(() => api.collaboration());
  const rows =
    c.data?.systems.filter(
      (s) =>
        (s.active && (!lineId || s.line_ids.includes(lineId))) ||
        s.id === value,
    ) || [];
  return (
    <div className="mf-field">
      <Choice
        label={label}
        value={value || ""}
        values={{
          "": "人工载体 / 未指定",
          ...(value && !rows.some((s) => s.id === value)
            ? { [value]: "已登记的系统引用" }
            : {}),
          ...Object.fromEntries(
            rows.map((s) => [
              s.id,
              `${s.name}${s.active ? "" : "（历史停用）"}`,
            ]),
          ),
        }}
        onChange={(v) => onChange(v || null)}
      />
      <button
        type="button"
        className="mf-link mf-small"
        onClick={() => void c.refresh().catch(() => {})}
      >
        {c.data ? "刷新可选系统" : "读取可选系统"}
      </button>
      {c.error && (
        <small role="alert">系统列表读取失败，可重试；已选引用保留。</small>
      )}
    </div>
  );
}
