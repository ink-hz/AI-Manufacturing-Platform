import type { ReadinessItem } from "./types";
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
