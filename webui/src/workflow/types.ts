import type { MaterialHandoffCommand, MaterialHandoffValue } from "./materialHandoffTypes";
export type * from "./materialHandoffTypes";
import type { OEMCommands, OEMValue, UnitAlias, ComponentHistory } from "./oemTypes";
export type * from "./oemTypes";
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
  | "material_task" | "material_expedite" | "material_handoff"
  | "npi" | "npi_issue" | "reusable_asset" | "asset_use" | "test_plan" | "test_run" | "calibration" | "component_link" | "arrival" | "authority_rule"
  | "rma" | "capa"
  | "shipment" | "closure"
  | "nonconformance" | "rework" | "release"
  | "eco"
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
export type ReleaseKind="manufacturing"|"quality"|"customer";
export type Measurement={name:string;unit:string;lower:string;upper:string;value:string};
export type TestScope={route_fingerprint:string;test_version:string;program_version:string;firmware_version:string;equipment_check_id:string};
export type UnitTest={id:string;attempt:number;outcome:"pass"|"fail";rework_order_id:string|null;occurred_at:string};
export type ClosureProgress={status:"blocked"|"ready"|"closed";recorded_count:number;blocking_reasons:string[]};
export type ProgressSummary={stages:ProjectDetail["stages"];blocking_objects:ObjectSummary[];blockers_truncated:boolean;fulfillment:ClosureProgress;quality:ClosureProgress;cost:ClosureProgress};
export interface OwnedTask {
  category: "readiness" | "source" | "acceptance" | "business";
  title: string;
  target: ObjectSummary;
  owner_id: string | null;
  owner_name: string;
}
export interface ActorTaskPage {
  items: OwnedTask[];
  /** Available count within existing per-project task bounds. */
  total: number;
  limit: number;
  offset: number;
  truncated: boolean;
}
export interface ProjectDetail extends Omit<ProjectCreate, "operation_id"> {
  tasks?: OwnedTask[];
  tasks_truncated?:boolean;
  progress?:ProgressSummary|null;
  release_kinds?:ReleaseKind[];
  quality_summary?:{first_tested:number;first_passed:number;final_good:number;scrapped:number;open_nonconformances:number}|null;
  id: string;
  version: number;
  allowed_actions: WorkflowCommand["action"][];
  stages: { stage: string; status: string; reason?: string }[];
  summary: QuantitySummary;
}
export interface CommandResult {
  integration?: import("./integrations/types").IntegrationStatus;
  current_project_version?: number | null;
  operation_id: string;
  project_id: string;
  project_version: number;
  object_type: string;
  object_id: string;
  exchange_id?: string | null;
  replayed: boolean;
}
export type MutationAcknowledgement = CommandResult | (Pick<CommandResult, "project_id" | "project_version" | "current_project_version"> & {object_type?:never;object_id?:never;exchange_id?:never});
export interface GrantResult extends Grant { project_version: number; }
export interface Grant {
  display_name?:string|null;
  scope: { kind: "project"; project_id: string };
  user_id: string;
  roles: string[];
  qualifications: string[];
  active: boolean;
}
export type GrantChange = Omit<Grant, "user_id" | "display_name"> & {
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
  route_steps: { station: string; instruction_version: string; material_consumption?:"required"|"none" }[];
  test_spec: TestSpec;
  firmware_version: string;
}
export type InboundKind = "receipt" | "iqc" | "customer_approval";
export type TypedInboundRecord={project_id:string;source:SourceRef;external_actor:string;signature:string} & (
  {object_type:"receipt";commitment_id:string;material_lot_id:string;quantity:string;unit:string} |
  {object_type:"iqc";receipt_system:string;receipt_external_id:string;accepted:string;rejected:string;evidence:string;manual_iqc_id?:string|null} |
  {object_type:"customer_approval";revision_id:string;customer_id:string;decision:"approved"|"rejected";evidence:string});
export interface ReceiptDetail {key:string;lot_id:string;owner_id:string;quantity:string;unit:string}
export interface ControlReceiptDetail {key:string;work_order_id:string;scope:"all"|"trial";state:"running"|"partial"}
export interface UnitReceiptDetail {key:string;unit_id:string;sn:string;state:"running"|"stopped"}
export interface SourceConfirmation {source:SourceRef;external_actor:string;signature:string;recorded_by:string;sequence:number}
export interface ExchangeValue {
  stock_basis_proof?:{mode:"mock"|"api";sources:{project_id:string;lot_id:string;owner_id:string;material_id:string;unit:string;quantity:string;source:SourceRef;sequence:number}[]}|null;
  kind:"exchange";action:string;policy_action:CommandFields["action"];system:string;business_key:string;
  mode:"mock"|"api"|"unavailable"|"file";phase:string;requested:string;accepted:string;rejected:string;unit:string;reason:string;
  discrepancies?:{sequence:number;owner_id:string;owner_name:string;reason:string;evidence:string;resolves_sequence:number|null}[];
  events:{sequence:number;phase:string;reason:string}[];reservation_id:string|null;
  source:SourceRef|null;source_object_type:InboundKind|null;
  receipt:{receipt_id:string;business_key:string;request_hash:string;source_object_id:string;source_version:number;sequence:number;
    phase:string;accepted_quantity:string;rejected_quantity:string;details:(ReceiptDetail|UnitReceiptDetail|ControlReceiptDetail|EcoReceiptDetail|ShipmentReceiptDetail|FreezeReceiptDetail)[];occurred_at:string;error:string|null}|null;
}
export interface EcoImpact {stock_basis?:Record<string,string>|null;opening_consumption?:string;stock_basis_complete?:boolean;id:string;type:"purchase"|"stock"|"wip"|"work_order"|"unit";object_id:string;title:string;owner_id:string;quantity:string;unit:string;scale:number;state:string;resolved_quantity:string;dispositions:{id:string;decision:"use_old"|"rework"|"return"|"scrap";quantity:string;evidence:string}[]}
export interface EcoValue {retentions?:{work_order_id:string;quantity:string;unit_ids:string[];evidence:string}[];implementation_outcome?:"pending"|"retained"|"cancelled"|"switched"|"mixed";unresolved_stock_basis_ids?:string[];kind:"eco";id:string;old_revision_id:string;new_revision_id:string|null;old_revision:string;new_revision:string|null;effective_work_order_ids:string[];effective_sn_ids:string[];reason:string;state:"open"|"closed";impacts:EcoImpact[];switches:{id:string;work_order_id:string;new_work_order_id:string|null;boundary:"split_remaining"|"cancel_remaining";quantity:string;retained_quantity:string;exchange_id:string;phase:string}[]}
export interface EcoReceiptDetail {key:string;effect:"cancel_remaining"|"create_replacement";work_order_id:string;revision_id:string;quantity:string;retained_quantity:string}
export interface ShipmentBox {box_id:string;unit_ids:string[]}
export interface AcceptanceIssue {id:string;title:string;owner_id:string;owner_name:string;required:boolean;resolved:boolean;evidence:string|null}
export interface DeliveryBalance {ordered:string;allocated:string;qualified:string;pending_shipment:string;shipped:string;signed:string;accepted:string;remaining_to_ship:string;remaining_to_accept:string;unit:string}
export interface ShipmentValue {kind:"shipment";id:string;order_line_id:string;unit_ids:string[];boxes:ShipmentBox[];exchange_id:string;state:"pending"|"accepted"|"rejected"|"held";quantity:string;shipped:string;signed:string;accepted:string;unit:string;remaining:DeliveryBalance;blocking_reasons:string[];issues:AcceptanceIssue[];facts:{id:string;action:"sign"|"accept";quantity:string;source:SourceRef|null;external_signatory:string;recorded_by:string}[]}
export interface OwnershipBalance {hold_reason?:string|null;received:string;consumed:string;scrapped:string;returned:string;balance:string;complete:boolean;unit:string;owner_id:string;material_id:string}
export interface MaterialScope {material_lot_id:string;material_id:string;owner_id:string;unit:string}
export type DeliveryCommand =
 | {action:"shipment.request";order_line_id:string;unit_ids:string[];boxes:ShipmentBox[];quantity:string;unit:string}
 | {action:"delivery.sign";shipment_id:string;quantity:string;source:SourceRef;external_signatory:string}
 | {action:"delivery.accept";shipment_id:string;quantity:string;source:SourceRef;external_signatory:string;issues:{title:string;owner_id:string;required:boolean}[]}
 | {action:"delivery.resolve_issue";issue_id:string;evidence:string}
 | {action:"closure.record";kind:"fulfillment"|"quality"|"cost";source:SourceRef;evidence:string}
 | ({action:"ownership.movement";movement:"return"|"raw_loss";quantity:string;supersedes_id?:string|null;source:SourceRef;external_signatory:string;evidence:string}&MaterialScope)
 | ({action:"ownership.reconcile";received:string;consumed:string;scrapped:string;returned:string;balance:string;source:SourceRef}&MaterialScope)
 | {action:"stock_basis.reconcile";eco_id:string;reservation_id:string};
export interface ShipmentReceiptDetail {key:string;unit_id:string;sn:string;work_order_id:string;order_line_id:string;box_id:string|null}
export interface ContractAgreement {id:string;supersedes_agreement_id:string|null;revision_id:string;contract:ProjectCreate["contract"];customer_id:string;external_signatory:string;evidence:string;project_version:number;recorded_at:string}
export type CommandFields =
  | {action:"mes_order.bind";work_order_id:string;shop_order:string;replace_binding_id:string|null;reason:string|null}
  | {action:"mes_order.refresh";work_order_id:string;binding_id:string}
  | {action:"material.need_time";requirement_id:string;need_at:string|null;evidence:string}
  | {action:"material_task.open";requirement_id:string;task_kind:"iqc"|"trace";receipt_id:string|null;handoff_id:string|null;assignee_id:string;note:string}
  | {action:"material_task.accept";task_id:string}
  | {action:"material_task.reassign";task_id:string;assignee_id:string;reason:string}
  | {action:"material_task.progress";task_id:string;note:string;expected_completion:string|null;blocked_reason:string|null;found_quantity:string|null;found_location:string|null}
  | {action:"material_task.close";task_id:string;outcome:"fulfilled"|"discrepancy"|"false_alarm"|"superseded";evidence:string;handoff_ids:string[]}
  | {action:"material_task.cancel";task_id:string;reason:string}
  | {action:"expedite.open";requirement_id:string;reason:string;impact:string}
  | {action:"expedite.progress";expedite_id:string;note:string}
  | {action:"expedite.close";expedite_id:string;outcome:"fulfilled"|"false_alarm"|"superseded";reason:string}
  | import("./integrations/types").IntegrationCommand
  | MaterialHandoffCommand
  | OEMCommands
  | {action:"contract.agree";revision_id:string;supersedes_agreement_id:string|null;contract:ProjectCreate["contract"];customer_id:string;external_signatory:string;evidence:string}
  | {action:"project.stage";stage:"S1"|"S2"|"S3"|"S4"|"S5"|"S6"|"S7"|"S8"|"S9";status:"pending"|"active"|"blocked"|"complete";reason:string}
  | FeedbackCommand
  | DeliveryCommand
  | {action:"test.record";source:SourceRef;unit_id:string;attempt:number;program_version:string;limit_version:string;firmware_version:string;measurements:Measurement[];rework_order_id?:string|null}
  | {action:"nonconformance.open";test_id:string;defect:string;evidence:string}
  | {action:"nonconformance.disposition";nonconformance_id:string;decision:"rework"|"scrap"|"concession";route_id?:string|null;route_steps:{station:string;instruction_version:string;material_consumption?:"required"|"none"}[];evidence:string}
  | {action:"rework.complete";rework_order_id:string;execution_event_ids:string[];test_ids:string[]}
  | {action:"release.decide";kind:ReleaseKind;unit_ids:string[];decision:"approved"|"rejected"|"conditional";evidence:string;customer_id?:string|null;revision_id?:string|null;customer_revision?:string|null;external_signatory?:string|null;method?:"manual"|null;source?:SourceRef|null}
  | {action:"eco.open";old_revision_id:string;new_revision_id:string|null;effective_work_order_ids:string[];effective_sn_ids:string[];reason:string}
  | {action:"eco.disposition";eco_id:string;impact_id:string;decision:"use_old"|"rework"|"return"|"scrap";quantity:string;evidence:string}
  | {action:"eco.switch";eco_id:string;target_work_order_id:string;new_revision_id:string|null;boundary:"split_remaining"|"cancel_remaining"|"retain_existing";retained_quantity?:string;evidence:string}
  | {action:"eco.close";eco_id:string}
  | {action:"unit.register";work_order_id:string;sns:string[]}
  | {action:"production.start";work_order_id:string;mode:"trial"|"bulk";unit_ids:string[];quantity:string}
  | {action:"production.interrupt";work_order_id:string;reason:string;kind:"S3"|"S4"|"other";interruption_id?:string|null;start_id?:string|null}
  | {action:"production.resume";interruption_id:string;plan_id:string;evidence:string;scope?:"all"|"trial"}
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
  assignee_id?: string | null;
  proposed_assignee_id?: string | null;
  action_capabilities?:{action:string;variants:Record<string,{ready:boolean|null;blocking_reasons:string[]}>}[];
  revision_family_id?:string|null;
  revision_id?:string|null;
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
  blocking_reasons?:string[];
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
  | MaterialHandoffValue
  | OEMValue
  | RmaValue | CapaValue
  | ShipmentValue
  | {kind:"closure";id:string;closure_kind:"fulfillment"|"quality"|"cost";status:"closed"|"blocked";source:SourceRef|null;evidence:string;blocking_reasons:string[]}
  | {kind:"test";current_qualified?:boolean|null;current_blocking_reasons?:string[];id:string;unit_id:string;revision_id:string;attempt:number;scope:TestScope;measurements:Measurement[];outcome:"pass"|"fail";rework_order_id:string|null;execution_event_ids:string[];source:SourceRef|null;actor_id:string;occurred_at:string;recorded_at:string}
  | {kind:"nonconformance";id:string;unit_id:string;test_id:string;defect:string;evidence:string;state:"open"|"rework"|"resolved"|"scrapped";rework_order_id:string|null;disposition:"rework"|"scrap"|null;disposition_evidence:string|null}
  | {kind:"rework";candidate_execution_events?:{id:string;station:string;route_version:string;occurred_at:string;result:"pass"|"fail";rework_order_id?:string|null}[];id:string;unit_id:string;nonconformance_id:string;revision_id:string;route_id:string;route_steps:{station:string;instruction_version:string;material_consumption?:"required"|"none"}[];state:"open"|"complete";execution_event_ids:string[];test_ids:string[]}
  | {kind:"release";id:string;release_kind:ReleaseKind;unit_ids:string[];decision:"approved"|"rejected";evidence:string;test_ids:string[];actor_id:string;customer_id:string|null;revision_id:string|null;customer_revision:string|null;external_signatory:string|null;method:"manual"|null;source:SourceRef|null;recorded_at:string}
  | EcoValue
  | ExchangeValue
  | {kind:"unit";aliases?:UnitAlias[];components?:ComponentHistory[];freeze_requested?:"frozen"|"unfrozen"|null;freeze_confirmed?:"frozen"|"unfrozen"|null;freeze_pending?:boolean;tests?:UnitTest[];test_total?:number;first_pass?:boolean|null;scrapped?:boolean;final_good?:boolean;id:string;project_id:string;work_order_id:string;revision_id:string;sn:string;state:"registered"|"start_pending"|"running"|"stopped";mode:"trial"|"bulk"|null;accepted_start_id:string|null;authority_start_accepted:boolean;execution_event_ids:string[];execution_event_total:number;execution_events:{id:string;source:SourceRef|null;status:"accepted"|"rejected";reason:string;station:string;route_version:string;program_version:string;firmware_version:string;result:"pass"|"fail";route_kind:"initial"|"rework";rework_order_id?:string|null;supersedes_event_id:string|null;occurred_at:string;recorded_at:string;material_uses:{lot_id:string;material_id:string;owner_id:string;quantity:string;unit:string}[]}[]}
  | {kind:"interruption";id:string;work_order_id:string;reason:string;exception_id:string|null;exception_kind:"S3"|"S4"|"other";requested_at:string;authority_stopped_at:string|null;resolved_at:string|null;trial_resumed_at?:string|null;superseded_by?:string|null;plan_id:string|null;stop_exchange_id:string;recovery_start_id:string|null;resume_exchange_id:string|null;stop_exchange_ids:string[];resume_exchange_ids:string[]}
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
      contract_agreement?:ContractAgreement|null;
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
      execution_events:{id:string;claimed_sn:string;source:SourceRef|null;status:"accepted"|"rejected";reason:string;station:string;route_version:string;program_version:string;firmware_version:string;result:"pass"|"fail";route_kind:"initial"|"rework";rework_order_id?:string|null;supersedes_event_id:string|null;occurred_at:string;recorded_at:string;material_uses:{lot_id:string;material_id:string;owner_id:string;quantity:string;unit:string}[]}[];
      remaining_obligation?:string;
      held_start_scopes?:{id:string;mode:"trial"|"bulk";sns:string[];exchange_id:string;receipt_id:string}[];
    }
  | {kind:"plan";state:"confirmed"|"rejected";reason:string;source:SourceRef;input_revision_ids:string[];input_order_versions:{order_line_id:string;version:number}[];requirement_ids:string[];cutoff:string|null}
  | {kind:"requirement";plan_id:string;lineage_id:string;supersedes_requirement_id:string|null;work_order_id:string;execution_scope:"trial"|"bulk"|"common";material_id:string;owner_id:string;quantity:string;unit:string;balance:MaterialBalance;unqualified_quantity:string;need_time_events?:{id:string;requirement_id:string;plan_id:string;need_at:string|null;evidence:string;actor_id:string;recorded_at:string}[]}
  | {kind:"commitment";requirement_id:string;type:"purchase"|"customer";owner_id:string;original_quantity:string;current_quantity:string;unit:string;original_due:string;current_due:string;source:SourceRef;promise_revisions:{source:SourceRef;quantity:string;current_due:string}[];material_lot_ids:string[];received:string;qualified:string;rejected:string}
  | {kind:"material_lot";freeze_requested?:"frozen"|"unfrozen"|null;freeze_confirmed?:"frozen"|"unfrozen"|null;freeze_pending?:boolean;ownership_balance?:OwnershipBalance;material_movements?:{id:string;movement:"return"|"raw_loss";quantity:string;supersedes_id:string|null;current:boolean;source:SourceRef|null;external_signatory:string;evidence:string}[];ownership_reconciliations?:{id:string;current:boolean;source:SourceRef|null;balance:OwnershipBalance}[];material_id:string;lot_id:string;owner_id:string;unit:string;scale:number;expiry:string;state:"active"|"frozen";source:SourceRef;received:string;qualified:string;rejected:string}
  | {kind:"receipt";quantity_state?:"pending_inspection"|"partially_inspected"|"accepted"|"rejected"|"mixed";next_step?:"inspect_remaining"|"review_rejected"|"await_authority_reservation";original_quantity?:string;corrections?:{sequence:number;received_delta:string;accepted_delta:string;rejected_delta:string;evidence:string}[];confirmations?:SourceConfirmation[];commitment_id:string;material_lot_id:string;quantity:string;unit:string;source:SourceRef;accepted:string;rejected:string;uninspected:string};
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
  onChanged(result: MutationAcknowledgement): void;
  onOpen(target: WorkflowTarget): void;
  onDirty(key: string, dirty: boolean): void;
  readOnly: boolean;
}

export type FeedbackCommand =
 | {action:"freeze.request";unit_ids:string[];lot_ids:string[];state:"frozen"|"unfrozen";reason:string}
 | {action:"rma.open";unit_id:string;shipment_id:string;reason:string;source:SourceRef}
 | {action:"capa.update";basis_sequence?:number|null;capa_id:string|null;rma_id:string;step:CapaStepName;description:string;evidence:string;effective?:boolean|null;action_kind?:"engineering"|"supplier"|"training"|"process"|null;implementation_evidence?:string|null;eco_id?:string|null}
 | {action:"capa.close";capa_id:string};
export type CapaStepName="containment"|"root_cause"|"correction"|"verification";
export type CapaStep={sequence:number;basis_sequence?:number|null;step:CapaStepName;description:string;evidence:string;effective:boolean|null;action_kind:"engineering"|"supplier"|"training"|"process"|null;implementation_evidence:string|null;eco_id:string|null};
export interface RmaValue {kind:"rma";id:string;unit_id:string;shipment_id:string;order_line_id:string;customer_id:string;revision_id:string;test_ids:string[];tests_truncated:boolean;reason:string;source:SourceRef|null;state:"open"|"closed"}
export interface CapaValue {kind:"capa";current_basis_sequence?:number|null;id:string;rma_id:string;state:"open"|"closed";steps:CapaStep[];steps_truncated:boolean;blocking_reasons:string[]}
export interface TraceResult {nodes:{id:string;kind:ObjectKind;project_id:string;title:string;customer_id:string|null}[];edges:{source_kind:ObjectKind;source_id:string;target_kind:ObjectKind;target_id:string;relation:"order"|"revision"|"work_order"|"consumed"|"test"|"prior_test"|"rework"|"release"|"shipment"|"rma"|"capa"}[];truncated:boolean}

export interface FreezeReceiptDetail {key:string;object_kind:"unit"|"material_lot";object_id:string;state:"frozen"|"unfrozen"}
