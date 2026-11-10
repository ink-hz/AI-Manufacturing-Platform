export type ObservationKind = 'production' | 'stopover';
export type CatalogKind = 'software' | 'software_versions' | 'configs' | 'config_versions' | 'review_orders';
export type SourceKind = ObservationKind | CatalogKind | 'evidence' | 'production_statistics' | 'stopover_statistics';
export interface ProductionStatus {
  source_namespace: string | null;
  source_project_id: string | null;
  configured: boolean;
  capabilities: Record<SourceKind | 'evidence_content', {available: boolean; reason: string | null}>;
}
export interface SourceProject { id: string; name: string }
export interface SourceProjectPage { items: SourceProject[]; limit: 100; has_more: boolean; next_before_id: string | null }
export interface TimeFilters { start: string; end: string; sn?: string; order_id?: string }
export interface ObservationFilters extends TimeFilters { kind: ObservationKind; device?: string; status?: '1' | '2' }
export interface CatalogFilters { parent_id?: string; before_id?: string }
export interface EvidenceFilters extends TimeFilters { before_id?: string }
export type ProductionRow = Record<string, unknown>;
export interface ProductionStatistics extends ProductionRow {
  records: number | string;
  distinct_sn: number | string;
  pass_records: number | string;
  fail_records: number | string;
  unknown_records: number | string;
  record_pass_ratio: number | null;
  consistency: 'single_query';
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
