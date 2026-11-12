export type QuantityOrigin = "native" | "manual" | "file" | "mock" | "unknown";
export type QuantityEnvironment = "production" | "test" | "development" | "mock" | "unknown";
export type QuantityCoverage = "complete" | "partial" | "failed" | "unknown";
export interface QuantitySource { reference: string; project_id: string; object_kind: string; object_id: string; system: string | null; source_type: string | null; external_id: string | null; version: string | number | null; namespace: string | null; origin: QuantityOrigin; environment: QuantityEnvironment; occurred_at: string | null; collected_at: string | null; coverage: QuantityCoverage; value: string | null; unit: string | null; meaning: string; }
export interface ProvenancedQuantity { value: string | null; unit: string; meaning: string; origins: QuantityOrigin[]; environments: QuantityEnvironment[]; fact_role: "confirmed" | "observation" | "unknown"; observed_at: string | null; collected_at: string | null; coverage: QuantityCoverage; source_refs: QuantitySource[]; input_refs: string[]; }
type QuantityMap = Record<string, ProvenancedQuantity>;
export type MaterialProblem = "all" | "attention" | "shortage" | "urgent" | "pending_iqc" | "unreceived" | "verification";
export interface MaterialFilters { search?: string; problem?: MaterialProblem; work_order_id?: string }
export interface MaterialIssue { code: string; title: string; object_kind: "requirement" | "receipt" | "material_handoff" | "material_lot" | "material_expedite"; object_id: string; quantity: string | null; quantity_fact?: ProvenancedQuantity; unit: string | null; task_id: string | null; assignee_id: string | null; proposed_assignee_id: string | null; assignee_name: string | null; proposed_assignee_name: string | null; next_action: "view_task" | "arrange_iqc" | "trace" | "expedite" | "view_object" | "confirm_time" | "check_allocation"; }
export function executionScopeLabel(scope: MaterialRequirement["execution_scope"]): string {
  return scope === "trial" ? "试产" : scope === "bulk" ? "量产" : scope === "common" ? "共用" : "范围待核对";
}
export interface MaterialRequirement {
  quantities?: QuantityMap;
  id: string;
  state?: "required" | "superseded";
  execution_scope?: "trial" | "bulk" | "common";
  work_order_id: string;
  material_id: string;
  owner_id: string;
  unit: string;
  required: string;
  received: string;
  qualified: string;
  rejected: string;
  reserved: string;
  shortage: string;
  in_transit: string;
  need_at: string | null;
  need_at_basis: string;
  coverage_issues: string[];
  confirmed_satisfied?: string | null;
  issues?: MaterialIssue[];
  need_time_history_count?: number;
  timing_risk?: "unknown" | "need_time_passed";
  expedite_ids: string[];
  receipt_ids: string[];
  handoff_ids: string[];
}
export interface MaterialProject {
  project_id: string;
  project_version: number;
  read_at: string;
  coverage_issues: string[];
  source_modes: string[];
  source_modes_scope?: "returned_quantities";
  work_orders: {
    id: string;
    title: string;
  }[];
  requirements: MaterialRequirement[];
  expedites: {
    id: string;
    requirement_id: string;
    expedite_number: string;
    state: string;
    reason: string;
    impact: string;
    progress: {
      note: string;
    }[];
    progress_total?: number;
    progress_truncated?: boolean;
  }[];
  receipts: {
    quantities?: QuantityMap;
    id: string;
    quantity: string;
    unit: string;
    qualified: string;
    rejected: string;
    uninspected: string;
  }[];
  handoffs: {
    quantities?: QuantityMap;
    id: string;
    handoff_number: string;
    material_lot_id: string;
    work_order_id: string | null;
    receiver_id: string;
    quantity: string;
    unit: string;
    from_location: string;
    to_location: string;
    receiver_name: string;
    receipt: {
      received_quantity: string;
      received_location: string;
    } | null;
  }[];
  material_task_counts: Record<string, number>;
  total: number;
  scope_total?: number;
  problem_counts?: Partial<Record<MaterialProblem, number>>;
  limit: number;
  offset: number;
}
export interface MaterialOverview {
  items: {
    project_id: string;
    name: string;
    product: string;
    work_order_count?: number;
    requirement_count: number;
    open_expedite_count: number;
    unreceived_handoff_count: number;
    open_material_task_count: number;
  }[];
  total: number;
  limit: number;
  offset: number;
  read_at: string;
}

export interface MaterialViewContext {
  offset: number;
  selected: string | null;
  filter: string;
  workOrder: string;
  taskOffset: number;
  problem?: MaterialProblem;
}
export const initialMaterialViewContext = (): MaterialViewContext => ({
  offset: 0,
  selected: null,
  filter: "",
  workOrder: "",
  taskOffset: 0,
  problem: "attention",
});

export interface MesOrderMaterialsData {
  work_order_id: string;
  can_manage: boolean;
  binding: { id: string; shop_order: string; environment: string; site_code: string; verified_at: string } | null;
  snapshot: { id: string; collected_at: string; total: number; components: { quantities?: QuantityMap; component_key: string; material_id: string; required_quantity: string; withdrawn_quantity: string | null; unit: string; storage_location: string | null }[] } | null;
}
