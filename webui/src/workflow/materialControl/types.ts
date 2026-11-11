export interface MaterialRequirement {
  id: string;
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
    id: string;
    quantity: string;
    unit: string;
    qualified: string;
    rejected: string;
    uninspected: string;
  }[];
  handoffs: {
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
}
export const initialMaterialViewContext = (): MaterialViewContext => ({
  offset: 0,
  selected: null,
  filter: "",
  workOrder: "",
  taskOffset: 0,
});

export interface MesOrderMaterialsData {
  work_order_id: string;
  can_manage: boolean;
  binding: { id: string; shop_order: string; environment: string; site_code: string; verified_at: string } | null;
  snapshot: { id: string; collected_at: string; total: number; components: { component_key: string; material_id: string; required_quantity: string; withdrawn_quantity: string | null; unit: string; storage_location: string | null }[] } | null;
}
