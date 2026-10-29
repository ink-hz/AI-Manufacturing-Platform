import type { ObjectKind } from "./types";
export type OEMWorkspaceName =
  "introduction" | "laboratory" | "supply" | "exchange";
export function oemObjectWorkspace(kind: ObjectKind): OEMWorkspaceName | null {
  if (["npi", "npi_issue", "reusable_asset", "asset_use"].includes(kind))
    return "introduction";
  if (["test_plan", "test_run", "calibration", "component_link"].includes(kind))
    return "laboratory";
  if (kind === "arrival") return "supply";
  if (kind === "authority_rule") return "exchange";
  return null;
}
export function oemActionWorkspace(action: string): OEMWorkspaceName | null {
  const prefix = action.split(".")[0];
  if (["npi", "asset"].includes(prefix)) return "introduction";
  if (
    ["test_plan", "test_run", "calibration", "component"].includes(prefix) ||
    action === "unit.alias"
  )
    return "laboratory";
  if (prefix === "arrival") return "supply";
  if (prefix === "authority") return "exchange";
  return null;
}
