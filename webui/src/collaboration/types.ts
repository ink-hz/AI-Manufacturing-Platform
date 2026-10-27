export type Method = "unknown" | "manual" | "file" | "api";
export interface Meta {
  id: string;
  version: number;
  created_at: string;
  updated_at: string;
  updated_by: string;
}
export interface Operation {
  operation_id: string;
  expected_version?: number;
}
export interface SystemFields {
  name: string;
  kind: string;
  line_ids: string[];
  business_owner: string;
  it_owner: string;
  usage:
    | "unverified"
    | "purchased_unused"
    | "used_bypassed"
    | "manual_effective"
    | "missing";
  method: Method;
  notes: string;
  active: boolean;
}
export interface SystemRecord extends SystemFields, Meta {}
export interface AuthorityFields {
  line_id: string;
  object_type:
    | "material"
    | "ebom"
    | "mbom"
    | "work_order"
    | "inventory"
    | "inspection"
    | "equipment";
  system_id: string;
  entry_point: string;
  owner: string;
  notes: string;
  active: boolean;
}
export interface Authority extends AuthorityFields, Meta {}
export interface PackageItem {
  id: string;
  kind:
    | "ebom"
    | "mbom"
    | "drawing"
    | "route"
    | "sop"
    | "firmware"
    | "test_program"
    | "test_spec"
    | "other";
  title: string;
  source_system_id: string | null;
  source_name: string;
  source_ref: string;
  revision: string;
  evidence: string;
  owner: string;
  status: "pending" | "verified" | "na";
  reason: string;
}
export interface PackageFields {
  title: string;
  product_ref: string;
  scope: string;
  provider: string;
  owner: string;
  customer_version: string;
  internal_version: string;
  approval_party: string;
  approval_status: "unknown" | "confirmed" | "not_required";
  approval_evidence: string;
  items: PackageItem[];
}
export interface EngineeringPackage extends PackageFields, Meta {
  project_id: string;
  family_id: string;
  revision: number;
  status: "draft" | "review" | "verified" | "returned" | "invalid";
  reason: string;
  supersedes_id: string | null;
}
export type PackageAction =
  | "submit"
  | "verify"
  | "return"
  | "revise"
  | "invalidate";
export interface HandoffFields {
  package_id: string;
  from_party: string;
  to_party: string;
  to_system_id: string | null;
  owner: string;
  due_date: string | null;
  method: Method;
  evidence: string;
  occurred_at: string | null;
}
export interface Handoff extends HandoffFields, Meta {
  project_id: string;
  project_name?: string;
  code: string;
  package_revision: number;
  received_revision: number | null;
  status: "draft" | "sent" | "received" | "returned" | "cancelled";
  reason: string;
}
export type HandoffAction = "send" | "receive" | "return" | "cancel";
export interface ReceiptAction {
  action: HandoffAction;
  received_revision: number | null;
  evidence: string;
  occurred_at: string | null;
  reason: string;
}
export interface ReadinessItem {
  id: string;
  kind:
    | "version"
    | "materials"
    | "equipment"
    | "people"
    | "first_article"
    | "customer"
    | "customer_material";
  label: string;
  required: boolean;
  owner: string;
  due_date: string | null;
  status: "pending" | "verified" | "blocked" | "na";
  evidence: string;
  source_ref: string;
  source_system_id: string | null;
  reason: string;
  valid_until: string | null;
  package_item_id: string | null;
  supply_mode: "unknown" | "self" | "customer" | "mixed";
  first_article_result: "unknown" | "planned" | "passed" | "failed" | "na";
}
export interface ReadinessFields {
  title: string;
  package_id: string;
  work_order_ref: string;
  scope: string;
  planned_use_date: string;
  required: boolean;
  owner: string;
  items: ReadinessItem[];
  supersedes_id?: string | null;
  supersedes_version?: number | null;
}
export interface Readiness extends ReadinessFields, Meta {
  project_id: string;
  package_revision: number;
  status: "pending" | "blocked" | "complete";
  superseded_by?: string | null;
}
export interface IssueFields {
  item_id: string;
  title: string;
  owner: string;
  due_date: string | null;
  priority: "normal" | "high" | "urgent";
  notes: string;
}
export interface ControlTarget {
  object_type: "package" | "handoff" | "readiness";
  object_id: string;
  item_id?: string | null;
}
export interface Attention extends ControlTarget {
  project_id: string;
  project_name: string;
  stage_id: string;
  title: string;
  reason: string;
  owner: string;
  due_date: string | null;
}
export interface ControlEvent extends Meta {
  object_type: string;
  object_id: string;
  actor: string;
  action: string;
  reason: string;
  occurred_at: string | null;
}
export interface Controls {
  packages: EngineeringPackage[];
  handoffs: Handoff[];
  readiness: Readiness[];
  events: ControlEvent[];
}
export interface Collaboration {
  systems: SystemRecord[];
  authorities: Authority[];
  handoffs: Handoff[];
  attention: Attention[];
}
