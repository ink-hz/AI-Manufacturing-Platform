import { fieldNames, localTime, text } from "./context";
import type { ProductionRow, Scope } from "./types";

/** Labels are bounded metadata owned by one project and an exact object identity. */
export interface BusinessNames {
  projectId: string;
  labels: Record<string, string>;
}
export const factNames = new Map([
  ["timestamp", "事件时间"], ["time", "事件时间"], ["sn", "SN"], ["barcode", "条码"],
  ["status", "结果"], ["errorcode", "错误码"], ["workstagesid", "阶段"],
  ["softwareid", "工具"], ["configlogsid", "配置"], ["version", "软件版本"],
  ["cversion", "配置版本"], ["devicename", "上位机"], ["orderid", "工具配置审核单"],
  ["workselectid", "测试项选择"], ["workstagesname", "阶段名称"], ["stage_name", "阶段名称"],
  ["softwarename", "工具名称"], ["software_name", "工具名称"],
  ["configlogsname", "配置名称"], ["config_name", "配置名称"], ["configname", "配置名称"],
  ["workselectname", "测试项名称"],
]);
const objects = new Map([
  ["workstagesid", { scope: "stage_id", aliases: ["workstagesname", "stage_name"], missing: "阶段名称暂不可用" }],
  ["softwareid", { scope: "software_id", aliases: ["softwarename", "software_name"], missing: "工具名称暂不可用" }],
  ["configlogsid", { scope: "config_log_id", aliases: ["configlogsname", "config_name", "configname"], missing: "配置名称暂不可用" }],
  ["workselectid", { scope: "workselect_id", aliases: ["workselectname"], missing: "测试项名称暂不可用" }],
]);
const name = (value: unknown) => typeof value === "string" && value.trim() ? value : undefined;
export const knownFacts = (row: ProductionRow) => Object.entries(row).filter(([key]) => factNames.has(key));
export function businessResult(value: unknown) {
  return String(value) === "1" ? "通过 PASS" : String(value) === "2" ? "失败 FAIL" : `结果未知（${text(value)}）`;
}
function objectName(key: string, value: unknown, row: ProductionRow, projectId: string, names?: BusinessNames) {
  const object = objects.get(key)!;
  const own = object.aliases.map(alias => name(row[alias])).find(Boolean);
  const owned = names?.projectId === projectId ? name(names.labels[`${object.scope}:${String(value)}`]) : undefined;
  return own || owned || object.missing;
}
export function factValue(key: string, row: ProductionRow, projectId: string, names?: BusinessNames) {
  if (objects.has(key)) return objectName(key, row[key], row, projectId, names);
  if (key === "timestamp" || key === "time") return localTime(row[key]);
  if (key === "status") return businessResult(row[key]);
  return text(row[key]);
}
export function scopeValue(key: string, value: unknown, projectId: string, names?: BusinessNames, evidence: ProductionRow[] = []) {
  const object = [...objects].find(([, item]) => item.scope === key);
  if (object) {
    const [native] = object;
    const row = evidence.find(row => row[native] != null && String(row[native]) === String(value)) || {};
    return objectName(native, value, row, projectId, names);
  }
  return key === "status" ? businessResult(value) : text(value);
}
export function scopeDescription(scope: Scope, projectId: string, names?: BusinessNames, evidence: ProductionRow[] = []) {
  return Object.entries(fieldNames).flatMap(([key, label]) => {
    const value = (scope as unknown as Record<string, unknown>)[key];
    return scope.missing_fields?.includes(key as never) ? [`${label}：源未提供`]
      : value !== undefined ? [`${label}：${scopeValue(key, value, projectId, names, evidence)}`] : [];
  }).join(" · ");
}
