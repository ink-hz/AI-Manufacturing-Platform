import type { PackageItem } from "../collaboration/types";
export interface WorkflowBootstrap {
  protocol: 1;
  allowed: boolean;
  available: boolean;
  workflow_available: boolean;
  workflow_access: boolean;
  can_edit: boolean;
  release: string;
  legacy_access: boolean;
  configuration_admin: boolean;
  dataset: {
    id: string;
    mode: "production" | "demo" | "test";
    label: string;
  } | null;
  user: { id: string; display_name: string };
  project_ids: string[];
}
export type WorkflowTarget = {
  projectId: string;
  kind: ObjectKind;
  id: string;
};
export type ObjectKind =
  | "demand"
  | "order_line"
  | "commitment_change"
  | "revision"
  | "work_order";
export interface SourceRef {
  system: string;
  object_type: string;
  external_id: string;
  version: number;
  mode: "manual" | "file" | "mock" | "api";
  occurred_at: string;
  collected_at: string;
  cutoff: string | null;
  evidence: string;
}
export interface Contract {
  customer_approval_required: boolean | "unknown";
  customer_release_required: boolean | "unknown";
  acceptance_required: boolean | "unknown";
  customer_revision: string;
  internal_revision: string;
  material_ownership_rules: string;
}
export interface ProjectCreate {
  operation_id: string;
  name: string;
  line_id: string;
  product: string;
  customer_id: string;
  mode: "internal" | "oem";
  unit: { code: string; scale: number };
  quantity: string;
  contract: Contract;
}
export type QuantitySummary = {
  original_order_quantity: string;
  current_order_quantity: string;
  allocated: string;
  produced_good: string;
  shipped: string;
  signed: string;
  accepted: string;
  remaining_to_ship: string;
  remaining_to_accept: string;
};
export interface ProjectDetail extends Omit<ProjectCreate, "operation_id"> {
  id: string;
  version: number;
  allowed_actions: WorkflowCommand["action"][];
  stages: { stage: string; status: string; reason?: string }[];
  summary: QuantitySummary;
}
export interface CommandResult {
  operation_id: string;
  project_id: string;
  project_version: number;
  object_type: string;
  object_id: string;
  exchange_id?: string | null;
  replayed: boolean;
}
export interface Grant {
  scope: { kind: "project"; project_id: string };
  user_id: string;
  roles: string[];
  qualifications: string[];
  active: boolean;
}
export type GrantChange = Omit<Grant, "user_id"> & {
  operation_id: string;
  expected_version: number;
  evidence: string;
};
export interface Disposition {
  object_type: "work_order" | "commitment" | "unit" | "shipment";
  object_id: string;
  decision: "retain" | "cancel" | "transfer" | "rework" | "return";
  evidence: string;
}
export interface TestSpec {
  version: string;
  program_version: string;
  measurements: { name: string; unit: string; lower: string; upper: string }[];
}
export interface RevisionFields {
  package_id: string;
  revision: string;
  customer_revision: string;
  internal_revision: string;
  items: PackageItem[];
  route_steps: { station: string; instruction_version: string }[];
  test_spec: TestSpec;
  firmware_version: string;
}
export type CommandFields =
  | {
      action: "demand.record";
      kind: "firm" | "forecast" | "inquiry";
      product: string;
      quantity: string;
      unit: string;
      due_date: string;
      source: SourceRef;
      supersedes_demand_id?: string | null;
    }
  | {
      action: "demand.review";
      demand_id: string;
      dimension:
        | "technical"
        | "material"
        | "capacity"
        | "commercial"
        | "quality";
      decision: "approved" | "rejected" | "unknown";
      evidence: string;
    }
  | {
      action: "order.register";
      demand_id: string;
      source: SourceRef;
      quantity: string;
      unit: string;
      due_date: string;
    }
  | {
      action: "order.change";
      order_line_id: string;
      new_quantity: string;
      new_due_date: string;
      cancel: boolean;
      reason: string;
      source: SourceRef;
    }
  | {
      action: "order.resolve_change";
      change_id: string;
      dispositions: Disposition[];
    }
  | {
      action: "order.allocate";
      order_line_id: string;
      work_order_id: string;
      quantity: string;
      unit: string;
    }
  | ({ action: "engineering.revision" } & RevisionFields)
  | {
      action: "engineering.handoff";
      revision_id: string;
      to_system: string;
      received_revision: string;
      decision: "accepted" | "rejected";
      evidence: string;
    }
  | {
      action: "engineering.customer_approval";
      revision_id: string;
      method: "manual";
      decision: "approved" | "rejected" | "unknown";
      customer_id: string;
      external_signatory: string;
      evidence: string;
    }
  | {
      action: "work_order.register";
      order_line_id: string;
      revision_id: string;
      source: SourceRef;
      quantity: string;
      unit: string;
      purpose: "trial" | "production";
      trial_quantity: string;
      planned_start: string;
      planned_end: string;
    }
  | {
      action: "readiness.record";
      work_order_id: string;
      kind: "equipment" | "people";
      reference: string;
      evidence: string;
      valid_until: string;
      decision: "verified" | "rejected";
    };
export type WorkflowCommand = CommandFields & {
  operation_id: string;
  expected_version: number;
};
export interface ObjectSummary {
  id: string;
  kind: ObjectKind;
  project_id: string;
  title: string;
  state: string;
  quantity: string | null;
  unit: string | null;
  source?: SourceRef | null;
  version: number;
  blocking_reasons: string[];
  next_actions: string[];
}
export interface Readiness {
  ready: boolean;
  checks: {
    kind: string;
    required: boolean;
    status: "ready" | "blocked" | "not_required";
    reason: string;
    evidence_ids: string[];
  }[];
  input_versions: Record<string, string | number>;
}
export interface WorkOrderImpactPreview {
  registered_quantity: string;
  total: number;
  shown: number;
  has_more: boolean;
  items: {
    id: string;
    source_system: string;
    external_id: string;
    quantity: string;
    unit: string;
  }[];
}
export type DomainValue =
  | {
      kind: "demand";
      demand_kind: string;
      product: string;
      quantity: string;
      unit: string;
      due_date: string;
      source: SourceRef;
      supersedes_demand_id: string | null;
      reviews: Record<string, string>;
    }
  | ({
      kind: "order_line";
      work_order_impact: WorkOrderImpactPreview;
      demand_id: string;
      original_quantity: string;
      current_quantity: string;
      unit: string;
      original_due: string;
      current_due: string;
      source: SourceRef;
      state: string;
    } & Omit<
      QuantitySummary,
      "original_order_quantity" | "current_order_quantity"
    >)
  | {
      kind: "commitment_change";
      order_line_id: string;
      old_quantity: string;
      new_quantity: string;
      unit: string;
      old_due: string;
      new_due: string;
      cancel: boolean;
      reason: string;
      source: SourceRef;
      state: string;
      impacts: {
        object_type: Disposition["object_type"];
        object_id: string;
        quantity: string;
        unit: string;
        decision: string | null;
        evidence: string | null;
      }[];
    }
  | ({
      kind: "revision";
      id: string;
      project_id: string;
      content_hash: string;
      handoffs: {
        id: string;
        to_system: string;
        received_revision: string;
        status: string;
        evidence: string;
      }[];
      customer_approvals: {
        id: string;
        method: "manual";
        recorded_by: string;
        customer_id: string;
        external_signatory: string;
        decision: string;
        evidence: string;
      }[];
    } & RevisionFields)
  | {
      kind: "work_order";
      order_line_id: string;
      revision_id: string;
      quantity: string;
      unit: string;
      purpose: string;
      trial_quantity: string;
      source: SourceRef;
      planned_start: string;
      planned_end: string;
      state: string;
      trial_readiness: Readiness;
      bulk_readiness: Readiness;
    };
export interface ObjectDetail {
  summary: ObjectSummary;
  value: DomainValue;
  relations: {
    relation: string;
    project_id: string;
    kind: ObjectKind;
    id: string;
  }[];
  evidence: { reference: string; source: SourceRef | null }[];
  history: {
    event_id: number;
    actor_id: string;
    action: string;
    occurred_at: string;
    recorded_at: string;
    evidence: { reference: string; source: SourceRef | null }[];
  }[];
}
export interface ObjectPage {
  items: ObjectSummary[];
  total: number;
  limit: number;
  offset: number;
}
export interface Dashboard {
  project_ids: string[];
  project_count: number;
  counts: Record<string, number>;
  cards: ObjectSummary[];
}
export interface WorkspaceProps {
  api: import("./api").WorkflowApi;
  project: ProjectDetail;
  onChanged(result: CommandResult): void;
  onOpen(target: WorkflowTarget): void;
  onDirty(key: string, dirty: boolean): void;
  readOnly: boolean;
}
