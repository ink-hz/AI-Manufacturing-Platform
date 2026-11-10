export type ObservationKind = "production" | "stopover";
export type CatalogKind =
  | "software"
  | "software_versions"
  | "configs"
  | "config_versions"
  | "review_orders";
export type SourceKind =
  | ObservationKind
  | CatalogKind
  | "evidence"
  | "production_statistics"
  | "stopover_statistics";
export interface ProductionStatus {
  source_namespace: string | null;
  source_project_id: string | null;
  configured: boolean;
  capabilities: Record<
    SourceKind | "evidence_content",
    { available: boolean; reason: string | null }
  >;
}
export interface SourceProject {
  id: string;
  name: string;
}
export interface SourceProjectPage {
  items: SourceProject[];
  limit: 100;
  has_more: boolean;
  next_before_id: string | null;
}
export interface TimeFilters {
  start: string;
  end: string;
  sn?: string;
  order_id?: string;
}
export interface ObservationFilters extends Scope {
  kind: ObservationKind;
  device?: string;
  status?: "1" | "2";
}
export interface CatalogFilters {
  parent_id?: string;
  before_id?: string;
}
export interface EvidenceFilters extends TimeFilters {
  before_id?: string;
  device?: string;
  tool_name?: string;
  missing_fields?: MissingField[];
}
export type ProductionRow = Record<string, unknown>;
export interface ProductionStatistics extends ProductionRow {
  records: number | string;
  distinct_sn: number | string;
  pass_records: number | string;
  fail_records: number | string;
  unknown_records: number | string;
  record_pass_ratio: number | null;
  consistency: "single_query";
}
export interface ProductionPage<Row = ProductionRow> {
  snapshot_id: string;
  source_namespace: string;
  source_project_id: string;
  source_kind: SourceKind;
  captured_at: string;
  expires_at: string;
  items: Row[];
  filters: Record<string, unknown>;
  complete: boolean;
  truncation_reason: string | null;
  next_before_id: string | null;
  redacted_fields: string[];
  offset: number;
  limit: number;
  captured_count: number;
  has_more: boolean;
}

export type MissingField =
  | "stage_id"
  | "software_id"
  | "config_log_id"
  | "software_version"
  | "config_version"
  | "device"
  | "error_code";
export interface Scope extends TimeFilters {
  stage_id?: string;
  software_id?: string;
  software_version?: string;
  config_log_id?: string;
  config_version?: string;
  device?: string;
  error_code?: string;
  barcode?: string;
  status?: "1" | "2";
  missing_fields?: MissingField[];
}
export type View =
  | "overview"
  | "project"
  | "anomalies"
  | "activity"
  | "device"
  | "history"
  | "records"
  | "catalog"
  | "compare";
export interface InvestigationContext extends Scope {
  view: View;
  symptom?: string;
  candidate_csn?: string;
  history_range?: TimeFilters;
  history_sn?: string;
  evidence_range?: TimeFilters;
  recent_range?: TimeFilters;
}
export type AnalysisView =
  | "summary"
  | "stages"
  | "errors"
  | "devices"
  | "activity"
  | "trend"
  | "versions";
export interface Aggregate {
  key: string;
  records: string;
  distinct_sn: string;
  pass_records: string;
  fail_records: string;
  unknown_records: string;
  failed_sn: string;
  first_time: string | null;
  last_time: string | null;
  denominator_records?: string;
  timestamp?: string;
  stage_id?: string | null;
  software_id?: string | null;
  config_log_id?: string | null;
  stage_name?: string;
  software_name?: string;
  device?: string | null;
  error_code?: string | null;
  software_version?: string | null;
  config_version?: string | null;
}
export interface Analysis {
  source_namespace: string;
  source_project_id: string;
  view: AnalysisView;
  captured_at: string;
  filters: Scope;
  items: Aggregate[];
  complete: boolean;
  truncation_reason: string | null;
  bucket_minutes?: number;
}
export interface Block {
  state: "ready" | "partial" | "unavailable";
  captured_at: string;
  complete: boolean;
  error: string | null;
  truncation_reason: string | null;
}
export interface OverviewItem extends SourceProject {
  state: Block["state"];
  statistics: Aggregate | null;
  trend: Aggregate[];
  latest_at: string | null;
  blocks: { statistics: Block; trend: Block; latest: Block };
}
export interface Overview {
  source_namespace: string;
  captured_at: string;
  complete: boolean;
  items: OverviewItem[];
  has_more: boolean;
  next_before_id: string | null;
}
export interface Selection {
  snapshot_id: string;
  offset: number;
}
export interface SavedSelection extends Selection {
  selection_id?: string;
  id?: string;
  source_kind: ObservationKind;
  descriptor: ProductionRow;
  fingerprint: string;
  captured_at?: string;
}
export interface SavedLog {
  source_log_id: string;
  descriptor: ProductionRow;
  state: string;
  match_basis?: string;
}
export interface ImpactCapture {
  state: string;
  captured_at: string;
  complete: boolean;
  counts: Record<string, string> | null;
  filters: Scope;
}
export interface Impact {
  state: string;
  captured_at: string;
  baseline: ImpactCapture;
  selected: ImpactCapture;
  failure: ImpactCapture;
  failure_records: { numerator: string | null; denominator: string | null };
  failed_involved_sn: { numerator: string | null; denominator: string | null };
}
export interface Investigation {
  id: string;
  source_namespace: string;
  source_project_id: string;
  owner_id: string;
  version: number;
  created_at: string;
  updated_at: string;
  expires_at: string;
  context: InvestigationContext;
  primary: SavedSelection | null;
  comparison: SavedSelection | null;
  logs: SavedLog[];
  note: string;
  impact: Impact | null;
  investigation_id?: string;
  origin_handoff_id?: string;
  origin_handoff_version?: number;
}
export interface CapturedLog extends Selection {
  source_log_id: string;
}
export type LogInput = string | CapturedLog;
export interface InvestigationPatch {
  context?: InvestigationContext;
  primary?: Selection | null;
  comparison?: Selection | null;
  logs?: LogInput[];
  note?: string;
}
export interface Candidate extends Selection {
  row: ProductionRow;
}
export interface Resolution {
  state:
    | "verified"
    | "ambiguous"
    | "changed"
    | "not_found"
    | "partial"
    | "unavailable";
  descriptor?: ProductionRow;
  candidates: Candidate[];
  complete: boolean;
  error?: string;
}
export interface ResolvedInvestigation {
  binding: {
    kind: "draft" | "handoff";
    id: string;
    version: number;
    primary_selection_id: string | null;
    comparison_selection_id: string | null;
  };
  primary: Resolution | null;
  comparison: Resolution | null;
  logs: (Resolution & { source_log_id: string })[];
  captured_at: string;
}
export interface ViewedEvent extends Candidate {
  kind: ObservationKind;
  captured_at: string;
  projectId: string;
}
