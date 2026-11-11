import { useEffect, useMemo, useState } from "react";
import { WorkflowError } from "../api";
import type {
  Aggregate,
  InvestigationContext,
  MissingField,
  Scope,
  View,
  ViewedEvent,
} from "./types";
export const missingOrder: MissingField[] = [
  "stage_id",
  "software_id",
  "config_log_id",
  "software_version",
  "config_version",
  "device",
  "error_code",
];
export const fieldNames: Record<string, string> = {
  stage_id: "阶段",
  software_id: "工具",
  software_version: "软件版本",
  config_log_id: "配置",
  config_version: "配置版本",
  device: "上位机",
  error_code: "错误码",
  status: "结果",
  sn: "SN",
  barcode: "条码",
  order_id: "工具配置审核单",
};
export function text(value: unknown): string {
  return value === null || value === undefined || value === ""
    ? "源未提供"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
}
export function localTime(value: unknown) {
  if (!value) return "源未提供";
  const d = new Date(
    typeof value === "number"
      ? value
      : /^\d{10,16}$/.test(String(value))
        ? Number(value)
        : String(value),
  );
  return isNaN(d.getTime())
    ? text(value)
    : d.toLocaleString(undefined, {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
        fractionalSecondDigits: d.getMilliseconds() ? 3 : undefined,
        hour12: false,
      });
}
export function localInput(value: string) {
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, -1);
}
export function today(): Scope {
  const end = new Date(),
    start = new Date(end);
  start.setHours(0, 0, 0, 0);
  if (+start === +end) end.setSeconds(1);
  return { start: start.toISOString(), end: end.toISOString() };
}
export function recent(minutes: number): Scope {
  const end = new Date();
  return {
    start: new Date(+end - minutes * 60000).toISOString(),
    end: end.toISOString(),
  };
}
export function previousDay(scope: Scope): Scope {
  return {
    ...scope,
    start: new Date(+new Date(scope.start) - 86400000).toISOString(),
    end: new Date(+new Date(scope.end) - 86400000).toISOString(),
  };
}
export function queryScope(context: InvestigationContext | Scope): Scope {
  const result: Record<string, unknown> = {
    start: context.start,
    end: context.end,
  };
  for (const k of [...Object.keys(fieldNames), "missing_fields"])
    if ((context as unknown as Record<string, unknown>)[k] !== undefined)
      result[k] = (context as unknown as Record<string, unknown>)[k];
  return result as unknown as Scope;
}
export function baseline(scope: Scope): Scope {
  const { error_code: _, status: __, ...rest } = scope;
  return {
    ...rest,
    missing_fields: rest.missing_fields?.filter((k) => k !== "error_code"),
  };
}
const dependencies: Record<string, string[]> = {
  stage_id: [
    "software_id",
    "software_version",
    "config_log_id",
    "config_version",
  ],
  software_id: ["software_version"],
  config_log_id: ["config_version"],
};
export function removeScope(scope: Scope, key: string): Scope {
  const next = { ...scope } as Scope & Record<string, unknown>;
  const cleared = [key, ...(dependencies[key] || [])];
  for (const field of cleared) delete next[field];
  next.missing_fields = next.missing_fields?.filter(
    (k) => !cleared.includes(k),
  );
  return next;
}
/** A user edit replaces the predicate, including its missing-value alternative. */
export function editScope(scope: Scope, edits: Partial<Scope>): Scope {
  let next = { ...scope };
  const predicates = [
    ...missingOrder,
    ...Object.keys(edits).filter(
      (k) =>
        !missingOrder.includes(k as MissingField) && k !== "missing_fields",
    ),
  ].flatMap((key) => {
    const exact = Object.prototype.hasOwnProperty.call(edits, key);
    const value = (edits as Record<string, unknown>)[key];
    const missing =
      !!edits.missing_fields?.includes(key as MissingField) &&
      (!exact || value === undefined);
    return exact || missing ? [{ key, value, missing }] : [];
  });
  // Clear only inherited predicates first. Explicit children are reapplied below,
  // even when a changed parent invalidates their old values in this same edit.
  for (const { key, value, missing } of predicates) {
    if (
      (scope as unknown as Record<string, unknown>)[key] !== value ||
      !!scope.missing_fields?.includes(key as MissingField) !== missing
    )
      next = removeScope(next, key);
  }
  for (const { key, value, missing } of predicates) {
    delete (next as unknown as Record<string, unknown>)[key];
    next.missing_fields = next.missing_fields?.filter((k) => k !== key);
    if (missing)
      next.missing_fields = missingOrder.filter(
        (k) => k === key || next.missing_fields?.includes(k),
      );
    else if (value !== undefined) next = { ...next, [key]: value };
  }
  return next;
}
export function drill(
  scope: Scope,
  item: Aggregate,
  fields: MissingField[],
): Scope {
  const edits: Partial<Scope> = {};
  for (const key of fields) {
    const value = item[key];
    if (value == null) (edits.missing_fields ||= []).push(key);
    else Object.assign(edits, { [key]: value });
  }
  return editScope(scope, edits);
}
/** Cursor ownership follows the effective read, rather than individual buttons. */
export function locationQueryKey(location: Location): string {
  const scope =
    location.view === "history"
      ? {
          start: (location.historyRange || location.scope).start,
          end: (location.historyRange || location.scope).end,
          sn: location.historySN,
        }
      : queryScope(location.scope);
  return JSON.stringify([
    location.projectId,
    location.view,
    Object.entries(scope)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => [k, Array.isArray(v) ? [...v].sort() : v]),
  ]);
}
export function errorText(error: unknown) {
  if (error instanceof WorkflowError) {
    if (error.code === "PRODUCTION_CAPABILITY_UNAVAILABLE")
      return "生产测试查询能力尚未配置，请联系管理员。";
    if (error.status === 401 || error.status === 403)
      return "无权访问产测管理，请重新登录或联系管理员。";
    if (error.status === 410)
      return "已过期，原观测参数暂不可恢复；请按条件重新核对。";
    if (
      error.code === "SOURCE_CONFIG_CHANGED" ||
      error.code === "INVESTIGATION_SOURCE_CHANGED" ||
      error.code === "SOURCE_CHANGED"
    )
      return "来源配置已变化，暂不可恢复";
    if (error.status === 404)
      return "源项目或调查不存在、已移除或来源配置已变化，暂不可恢复";
  }
  return "数据源暂不可用，请稍后重试。";
}
export interface Read<T> {
  data: T | null;
  error: string;
  loading: boolean;
}
export function useRead<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
  enabled = true,
  identityDeps = deps,
): Read<T> & { retry: () => void } {
  const key = useMemo(() => ({}), [...identityDeps, enabled]);
  const [state, setState] = useState<Read<T> & { key: object }>({
      key,
      data: null,
      error: "",
      loading: enabled,
    }),
    [tick, setTick] = useState(0);
  useEffect(() => {
    const c = new AbortController();
    setState((old) => ({
      key,
      data: enabled && old.key === key ? old.data : null,
      error: "",
      loading: enabled,
    }));
    if (enabled)
      load(c.signal)
        .then((data) => {
          if (!c.signal.aborted)
            setState({ key, data, error: "", loading: false });
        })
        .catch((e) => {
          if (!c.signal.aborted)
            setState((old) => ({
              key,
              data: old.key === key ? old.data : null,
              error: errorText(e),
              loading: false,
            }));
        });
    return () => c.abort();
  }, [...deps, enabled, tick, key]);
  return {
    ...(state.key === key
      ? state
      : { data: null, error: "", loading: enabled }),
    retry: () => setTick((t) => t + 1),
  };
}
export interface Location {
  view: View;
  projectId: string;
  scope: Scope;
  labels: Record<string, string>;
  historySN?: string;
  savedSymptom?: string;
  historyRange?: Scope;
  recentRange?: Scope;
  evidenceRange?: Scope;
  candidateCSN?: string;
  inspected?: ViewedEvent;
  catalog?:
    | "software"
    | "configs"
    | "review_orders"
    | "software_versions"
    | "config_versions";
  parentId?: string;
  cursor?: {
    id: string;
    offset: number;
    limit: number;
    kind?: "production" | "stopover";
  };
  readGeneration?: number;
  scroll?: number;
  selectedStage?: boolean;
  selectedError?: boolean;
  inherited: boolean;
  parentRead?: {
    captured_at: string;
    records: string;
    distinct_sn: string;
    scope: Scope;
  };
}

export function sourceName(
  location: Location,
  field: "stage_id" | "software_id",
  value: unknown,
) {
  if (
    value === null ||
    value === undefined ||
    ["", "0", "-1"].includes(String(value))
  )
    return "源未提供";
  return (
    location.labels[`${field}:${String(value)}`] ||
    (String(location.scope[field]) === String(value)
      ? location.labels[field]
      : undefined) ||
    `${fieldNames[field]} ${String(value)}（名称未取得）`
  );
}

export function matchesContext(
  context: InvestigationContext,
  row: Record<string, unknown>,
) {
  const fields: Record<string, string> = {
    sn: "sn",
    barcode: "barcode",
    device: "devicename",
    status: "status",
    error_code: "errorcode",
    stage_id: "workstagesid",
    software_id: "softwareid",
    software_version: "version",
    config_log_id: "configlogsid",
    config_version: "cversion",
    order_id: "orderid",
  };
  for (const [key, native] of Object.entries(fields)) {
    const value = (context as unknown as Record<string, unknown>)[key];
    if (
      value !== undefined &&
      row[native] != null &&
      String(row[native]) !== String(value)
    )
      return false;
  }
  for (const key of context.missing_fields || []) {
    const value = row[fields[key]];
    if (
      value !== null &&
      value !== undefined &&
      value !== "" &&
      (!key.endsWith("_id") || !["0", "-1"].includes(String(value)))
    )
      return false;
  }
  const when = new Date(String(row.timestamp));
  return (
    !Number.isFinite(+when) ||
    (+when >= +new Date(context.start) && +when < +new Date(context.end))
  );
}

export function investigationContextFromLocation(
  loc: Location,
): InvestigationContext {
  return {
    ...loc.scope,
    view: loc.view,
    history_sn: loc.historySN || undefined,
    symptom:
      loc.savedSymptom ||
      [
        loc.labels.project || `源项目 ${loc.projectId}`,
        loc.scope.stage_id
          ? loc.labels[`stage_id:${loc.scope.stage_id}`] || loc.labels.stage_id
          : undefined,
        loc.scope.software_id
          ? loc.labels[`software_id:${loc.scope.software_id}`] ||
            loc.labels.software_id
          : undefined,
        loc.scope.error_code ? `错误码 ${loc.scope.error_code}` : undefined,
      ]
        .filter(Boolean)
        .join(" · ")
        .slice(0, 1000),
    recent_range: loc.recentRange,
    evidence_range: loc.evidenceRange,
    candidate_csn: loc.candidateCSN,
    ...(loc.view === "history"
      ? {
          history_range: loc.historyRange || {
            start: loc.scope.start,
            end: loc.scope.end,
          },
        }
      : {}),
  };
}
