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
  | "work_order"
  | "plan" | "requirement" | "commitment" | "material_lot" | "receipt" | "reservation" | "exchange" | "unit" | "interruption" | "test";
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
  current_project_version?: number | null;
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
export type InboundKind = "receipt" | "iqc" | "customer_approval";
export type TypedInboundRecord={project_id:string;source:SourceRef;external_actor:string;signature:string} & (
  {object_type:"receipt";commitment_id:string;material_lot_id:string;quantity:string;unit:string} |
  {object_type:"iqc";receipt_system:string;receipt_external_id:string;accepted:string;rejected:string;evidence:string;manual_iqc_id?:string|null} |
  {object_type:"customer_approval";revision_id:string;customer_id:string;decision:"approved"|"rejected";evidence:string});
export interface ReceiptDetail {key:string;lot_id:string;owner_id:string;quantity:string;unit:string}
export interface UnitReceiptDetail {key:string;unit_id:string;sn:string;state:"running"|"stopped"}
export interface SourceConfirmation {source:SourceRef;external_actor:string;signature:string;recorded_by:string;sequence:number}
export interface ExchangeValue {
  kind:"exchange";action:string;policy_action:CommandFields["action"];system:string;business_key:string;
  mode:"mock"|"api"|"unavailable"|"file";phase:string;requested:string;accepted:string;rejected:string;unit:string;reason:string;
  discrepancies?:{sequence:number;owner_id:string;owner_name:string;reason:string;evidence:string;resolves_sequence:number|null}[];
  events:{sequence:number;phase:string;reason:string}[];reservation_id:string|null;
  source:SourceRef|null;source_object_type:InboundKind|null;
  receipt:{receipt_id:string;business_key:string;request_hash:string;source_object_id:string;source_version:number;sequence:number;
    phase:string;accepted_quantity:string;rejected_quantity:string;details:(ReceiptDetail|UnitReceiptDetail)[];occurred_at:string;error:string|null}|null;
}
export type CommandFields =
  | {action:"unit.register";work_order_id:string;sns:string[]}
  | {action:"production.start";work_order_id:string;mode:"trial"|"bulk";unit_ids:string[];quantity:string}
  | {action:"production.interrupt";work_order_id:string;reason:string;kind:"S3"|"S4"|"other";interruption_id?:string|null;start_id?:string|null}
  | {action:"production.resume";interruption_id:string;plan_id:string;evidence:string}
  | {action:"execution.record";source:SourceRef;work_order_id:string;sn:string;station:string;route_version:string;program_version:string;firmware_version:string;material_uses:{lot_id:string;quantity:string;unit:string}[];result:"pass"|"fail";occurred_at:string;supersedes_event_id?:string|null;rework_order_id?:string|null}
  | {action:"first_article.record";work_order_id:string;unit_ids:string[];test_ids:string[];inspection_id:string}
  | {action:"reservation.request";work_order_id:string;requirement_id:string;lot_id:string;quantity:string;unit:string}
  | {action:"exchange.dispatch";exchange_id:string}
  | {action:"exchange.query";exchange_id:string}
  | {action:"source.pull";system:string;object_type:InboundKind;external_id:string}
  | {action:"source.import";object_type:InboundKind;rows:TypedInboundRecord[]}
  | {action:"source.import_file";object_type:InboundKind;format:"json"|"csv";content_base64:string}
  | {action:"exchange.reconcile";exchange_id:string;source:SourceRef;object_type:"reservation"|InboundKind;source_version:number;
      details:ReceiptDetail[];resolution:"compare"|"accept_authority";evidence:string}

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
    }
  | { action: "material.define"; material_id: string; lot_id: string; owner_id: string; unit: string; scale: number; expiry: string; source: SourceRef }
  | { action: "plan.receive"; source: SourceRef; input_revision_ids: string[]; input_order_versions: {order_line_id:string;version:number}[]; requirements: {work_order_id:string;execution_scope:"trial"|"bulk"|"common";material_id:string;owner_id:string;quantity:string;unit:string}[] }
  | { action: "supply.commit"; commitment_id?: string | null; requirement_id: string; type:"purchase"|"customer"; owner_id:string; quantity:string; unit:string; original_due:string; current_due:string; source:SourceRef }
  | { action: "supply.receive"; commitment_id:string; material_lot_id:string; quantity:string; unit:string; source:SourceRef }
  | { action: "supply.inspect"; receipt_id:string; accepted:string; rejected:string; evidence:string };
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
  material_balance?: MaterialBalance | null;
}
export interface MaterialBalance {
  required: string;
  in_transit: string;
  received: string;
  qualified: string;
  rejected: string;
  reserved: string;
  shortage: string;
  unit: string;
  cutoff: string | null;
  source_version: number;
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
  | ExchangeValue
  | {kind:"unit";id:string;project_id:string;work_order_id:string;revision_id:string;sn:string;state:"registered"|"start_pending"|"running"|"stopped";mode:"trial"|"bulk"|null;accepted_start_id:string|null;authority_start_accepted:boolean;execution_event_ids:string[];execution_event_total:number;execution_events:{id:string;source:SourceRef;status:"accepted"|"rejected";reason:string;station:string;route_version:string;program_version:string;firmware_version:string;result:"pass"|"fail";route_kind:"initial"|"rework";supersedes_event_id:string|null;occurred_at:string;recorded_at:string;material_uses:{lot_id:string;material_id:string;owner_id:string;quantity:string;unit:string}[]}[]}
  | {kind:"interruption";id:string;work_order_id:string;reason:string;exception_id:string|null;exception_kind:"S3"|"S4"|"other";requested_at:string;authority_stopped_at:string|null;resolved_at:string|null;plan_id:string|null;stop_exchange_id:string;recovery_start_id:string|null;resume_exchange_id:string|null;stop_exchange_ids:string[];resume_exchange_ids:string[]}
  | {kind:"reservation";requirement_id:string;work_order_id:string;material_lot_id:string;requested:string;confirmed:string;remaining:string;unit:string;source_version:number;authority_receipt_id:string|null;exchange_id:string}
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
        method: "manual" | "file" | "mock" | "api";
        source?: SourceRef | null;
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
      execution_event_total:number;
      execution_events:{id:string;claimed_sn:string;source:SourceRef;status:"accepted"|"rejected";reason:string;station:string;route_version:string;program_version:string;firmware_version:string;result:"pass"|"fail";route_kind:"initial"|"rework";supersedes_event_id:string|null;occurred_at:string;recorded_at:string;material_uses:{lot_id:string;material_id:string;owner_id:string;quantity:string;unit:string}[]}[];
      held_start_scopes?:{id:string;mode:"trial"|"bulk";sns:string[];exchange_id:string;receipt_id:string}[];
    }
  | {kind:"plan";state:"confirmed"|"rejected";reason:string;source:SourceRef;input_revision_ids:string[];input_order_versions:{order_line_id:string;version:number}[];requirement_ids:string[];cutoff:string|null}
  | {kind:"requirement";plan_id:string;lineage_id:string;supersedes_requirement_id:string|null;work_order_id:string;execution_scope:"trial"|"bulk"|"common";material_id:string;owner_id:string;quantity:string;unit:string;balance:MaterialBalance;unqualified_quantity:string}
  | {kind:"commitment";requirement_id:string;type:"purchase"|"customer";owner_id:string;original_quantity:string;current_quantity:string;unit:string;original_due:string;current_due:string;source:SourceRef;promise_revisions:{source:SourceRef;quantity:string;current_due:string}[];material_lot_ids:string[];received:string;qualified:string;rejected:string}
  | {kind:"material_lot";material_id:string;lot_id:string;owner_id:string;unit:string;scale:number;expiry:string;state:"active"|"frozen";source:SourceRef;received:string;qualified:string;rejected:string}
  | {kind:"receipt";original_quantity?:string;corrections?:{sequence:number;received_delta:string;accepted_delta:string;rejected_delta:string;evidence:string}[];confirmations?:SourceConfirmation[];commitment_id:string;material_lot_id:string;quantity:string;unit:string;source:SourceRef;accepted:string;rejected:string;uninspected:string};
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
