import type {
  ObjectKind,
  SourceRef,
  Measurement,
  TestScope,
  TestSpec,
  MaterialBalance,
  CapaStep,
} from "./types";
export type Origin = "manual" | "demo";
export interface Attribution {
  actor_id: string;
  recorded_at: string;
  evidence: string;
}
export type Decision = "pass" | "blocked" | "not_applicable";
export interface ReviewCheck {
  code: string;
  required: boolean;
  decision: Decision;
  evidence: string;
  reason: string;
}
export interface AssetContent {
  title: string;
  category: "check" | "process_module" | "test_module";
  product_families: string[];
  execution_content: string;
  verification_method: string;
}
export interface IssueResolution {
  verified_cause: string;
  countermeasure: string;
  verification_evidence: string;
  test_ids: string[];
  actor_id: string;
  recorded_at: string;
}
export interface NPIValue {
  kind: "npi";
  revision_id: string;
  product_family: string;
  scenario: "first_introduction" | "change_validation";
  required_checks: string[];
  work_order_ids: string[];
  state: "open" | "approved";
  bulk_eligible: boolean;
  blocking_reasons: string[];
  reviews: {
    id: string;
    checks: ReviewCheck[];
    actor_id: string;
    recorded_at: string;
  }[];
  trials: {
    id: string;
    work_order_id: string;
    test_ids: string[];
    outcome: "pass" | "fail";
    qualified: boolean;
    evidence: string;
    actor_id: string;
    recorded_at: string;
  }[];
  approvals: {
    id: string;
    generation: number;
    evidence: string;
    actor_id: string;
    recorded_at: string;
  }[];
}
export interface NPIIssueValue {
  kind: "npi_issue";
  npi_id: string;
  phenomenon: string;
  risk: string;
  containment: string;
  state: "open" | "resolved" | "unverified";
  verified: boolean;
  resolution: IssueResolution | null;
  resolutions: IssueResolution[];
}
export interface ReusableAssetValue {
  kind: "reusable_asset";
  issue_id: string;
  content: AssetContent;
  public_content: AssetContent | null;
  supersedes_id: string | null;
  revision: number;
  published_by: string;
  published_at: string;
}
export interface AssetUseValue {
  kind: "asset_use";
  npi_id: string;
  asset_revision_id: string;
  revision: number;
  snapshot: AssetContent;
  required: boolean;
  verifications: ({ id: string; decision: Decision } & Attribution)[];
}
export interface PublicAssetEntry {
  asset_revision_id: string;
  revision: number;
  content: AssetContent;
}
export interface PublicAssetPage {
  items: PublicAssetEntry[];
  total: number;
  limit: number;
  offset: number;
}
export interface Parameter {
  name: string;
  value: string;
  unit: string;
}
export interface Curve {
  name: string;
  x_unit: string;
  y_unit: string;
  points: { x: string; y: string }[];
}
export interface RawEvidence {
  origin: Origin;
  curves: Curve[];
  logs: string[];
}
export interface TestPlanValue {
  kind: "test_plan";
  id: string;
  revision_id: string;
  level: string;
  station: string;
  equipment: string;
  fixture: string;
  algorithm_version: string;
  test_spec: TestSpec;
  firmware_version: string;
  revision_hash: string;
  actor_id: string;
  recorded_at: string;
  state: "published";
}
export type FinishState = "completed" | "aborted" | "invalid";
export interface RunFinish extends Attribution {
  source: SourceRef;
  state: FinishState;
  measurements: Measurement[];
  raw: RawEvidence;
  raw_digest: string;
  outcome: "pass" | "fail" | null;
  test_id: string | null;
}
export interface TestRunValue {
  kind: "test_run";
  id: string;
  plan_id: string;
  unit_id: string;
  revision_id: string;
  rework_order_id: string | null;
  attempt: number;
  accepted_start_id: string;
  scope: TestScope;
  execution_event_ids: string[];
  actor_id: string;
  recorded_at: string;
  state: "running" | FinishState;
  outcome: "pass" | "fail" | null;
  test_id: string | null;
  raw: RawEvidence | null;
  raw_digest: string | null;
  finish: RunFinish | null;
}
export interface CalibrationValue extends Attribution {
  kind: "calibration";
  id: string;
  run_id: string;
  unit_id: string;
  algorithm_version: string;
  parameters: Parameter[];
  parameter_digest: string;
  source_identity: string;
  source_version: string;
  origin: Origin;
  state: "pending" | "confirmed";
  confirmation:
    | (Attribution & {
        origin: Origin;
        source_identity: string;
        source_version: string;
        readback: Parameter[];
        parameter_digest: string;
      })
    | null;
}
export interface ComponentHistory extends Attribution {
  id: string;
  unit_id: string;
  material_id: string;
  component_serial: string;
  lot_id: string | null;
  origin: Origin;
  state: "installed" | "removed";
  removal: Attribution | null;
}
export interface UnitAlias extends Attribution {
  id: string;
  customer_id: string;
  customer_serial: string;
}
export interface AuthorityRuleValue extends Attribution {
  kind: "authority_rule";
  id: string;
  object_category: ObjectKind;
  business_scope: string;
  system: string;
  responsible_identity: string;
  origin: Origin;
  revision: number;
  supersedes_id: string | null;
  active: boolean;
  state: "registered" | "verified";
  connection_state: "unconnected" | "demo";
  verification: {
    contract_evidence: string;
    actor_id: string;
    recorded_at: string;
  } | null;
}
export interface ArrivalValue {
  kind: "arrival";
  id: string;
  arrival_number: string;
  location: string;
  package_count: number;
  description: string;
  source: SourceRef;
  actor_id: string;
  recorded_at: string;
  state: "unlinked" | "matched";
  receipt_id: string | null;
  matches: ({
    id: string;
    receipt_id: string;
    previous_receipt_id: string | null;
    correction_reason: string | null;
  } & Attribution)[];
}
export type OEMValue =
  | NPIValue
  | NPIIssueValue
  | ReusableAssetValue
  | AssetUseValue
  | TestPlanValue
  | TestRunValue
  | CalibrationValue
  | (ComponentHistory & { kind: "component_link" })
  | AuthorityRuleValue
  | ArrivalValue;
export type OEMCommands =
  | {
      action: "npi.open";
      revision_id: string;
      product_family: string;
      scenario: "first_introduction" | "change_validation";
      required_checks: string[];
      work_order_ids: string[];
    }
  | { action: "npi.review"; npi_id: string; checks: ReviewCheck[] }
  | {
      action: "npi.trial";
      npi_id: string;
      work_order_id: string;
      test_ids: string[];
      evidence: string;
    }
  | {
      action: "npi.issue";
      npi_id: string;
      phenomenon: string;
      risk: string;
      containment: string;
    }
  | {
      action: "npi.resolve";
      issue_id: string;
      verified_cause: string;
      countermeasure: string;
      verification_evidence: string;
      test_ids: string[];
    }
  | { action: "npi.approve"; npi_id: string; evidence: string }
  | {
      action: "asset.publish";
      issue_id: string;
      content: AssetContent;
      public_content: AssetContent | null;
      supersedes_id: string | null;
    }
  | {
      action: "asset.apply";
      npi_id: string;
      asset_revision_id: string;
      required: boolean;
    }
  | {
      action: "asset.verify";
      asset_use_id: string;
      decision: Decision;
      evidence: string;
    }
  | {
      action: "test_plan.publish";
      revision_id: string;
      level: string;
      station: string;
      equipment: string;
      fixture: string;
      algorithm_version: string;
    }
  | {
      action: "test_run.start";
      plan_id: string;
      unit_id: string;
      rework_order_id: string | null;
    }
  | {
      action: "test_run.finish";
      run_id: string;
      state: FinishState;
      source: SourceRef;
      measurements: Measurement[];
      raw: RawEvidence;
      reason: string | null;
    }
  | {
      action: "calibration.record";
      run_id: string;
      algorithm_version: string;
      parameters: Parameter[];
      source_identity: string;
      source_version: string;
      origin: Origin;
      evidence: string;
    }
  | {
      action: "calibration.confirm";
      calibration_id: string;
      readback: Parameter[];
      origin: Origin;
      source_identity: string;
      source_version: string;
      evidence: string;
    }
  | {
      action: "component.install";
      unit_id: string;
      material_id: string;
      component_serial: string;
      lot_id: string | null;
      origin: Origin;
      evidence: string;
    }
  | { action: "component.remove"; component_link_id: string; evidence: string }
  | {
      action: "unit.alias";
      unit_id: string;
      customer_serial: string;
      evidence: string;
    }
  | {
      action: "authority.register";
      object_category: ObjectKind;
      business_scope: string;
      system: string;
      responsible_identity: string;
      evidence: string;
      origin: Origin;
    }
  | { action: "authority.verify"; rule_id: string; contract_evidence: string }
  | {
      action: "arrival.record";
      arrival_number: string;
      location: string;
      package_count: number;
      description: string;
      source: SourceRef;
    }
  | {
      action: "arrival.match";
      arrival_id: string;
      receipt_id: string;
      evidence: string;
      correction_reason: string | null;
    };
export type AssistanceKind =
  "introduction" | "materials" | "change" | "knowledge" | "testing" | "quality";
export interface AssistanceTarget {
  scope: "project" | "public_catalog";
  project_id: string | null;
  kind: ObjectKind;
  id: string;
}
export interface AssistanceItem {
  target: AssistanceTarget;
  title: string;
  state: string;
  suggestion: string;
  blockers: string[];
  unknowns: string[];
  evidence: string[];
  related_targets: AssistanceTarget[];
  source: SourceRef | null;
  quantities: {
    accepted: string;
    rejected: string;
    pending: string;
    unit: string;
  } | null;
  material_balance: MaterialBalance | null;
  public_asset: PublicAssetEntry | null;
  testing: {
    revision_id: string;
    program_version: string;
    run_state: "running" | FinishState | null;
    outcome: "pass" | "fail" | null;
    measurements: Measurement[];
    failed_measurements: Measurement[];
    current_qualified: boolean | null;
    origin: Origin | null;
    comparison_basis: "same_revision_and_program";
    similar_targets: AssistanceTarget[];
  } | null;
  quality_outline: {
    format: "8d_evidence_draft";
    facts: string[];
    containment: CapaStep[];
    registered_causes: CapaStep[];
    actions: CapaStep[];
    verification: CapaStep[];
    disposition: string | null;
    disposition_evidence: string | null;
    missing_fields: string[];
  } | null;
  evidence_truncated: boolean;
}
export interface AssistanceResult {
  project_id: string;
  kind: AssistanceKind;
  mode: "rules";
  state: "evidence_available" | "no_evidence";
  source_scope: "authorized_project_and_approved_public_catalog";
  items: AssistanceItem[];
  unknowns: string[];
  truncated: boolean;
}
