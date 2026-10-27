import type { ReadinessItem, ReadinessFields } from "./types";
import { readinessKinds } from "./labels";
export const newCheck = (
  kind: ReadinessItem["kind"] = "version",
): ReadinessItem => ({
  id: crypto.randomUUID(),
  kind,
  label: readinessKinds[kind],
  required: true,
  owner: "",
  due_date: null,
  status: "pending",
  evidence: "",
  source_ref: "",
  source_system_id: null,
  reason: "",
  valid_until: null,
  package_item_id: null,
  supply_mode: "unknown",
  first_article_result: "unknown",
});

export function validateReadinessCreate(
  body: ReadinessFields,
  replacement: boolean,
) {
  if (body.required && !body.items.some((i) => i.required))
    throw new Error("纳入项目必需准备时，至少选择一个必需准备项");
  if (
    body.items.some(
      (i) => i.kind === "version" && !i.package_item_id && i.status !== "na",
    )
  )
    throw new Error("替代核对必须选择适用的冻结资料项");
  if (body.items.some((i) => i.status === "na" && !i.reason.trim()))
    throw new Error("不适用需填写原因");
  if (
    replacement &&
    body.items.some(
      (i) =>
        i.status === "na" &&
        ![i.owner, i.source_ref, i.evidence, i.reason].every((v) => v.trim()),
    )
  )
    throw new Error("本次不适用需重新填写负责人、来源、凭据和原因");
}
