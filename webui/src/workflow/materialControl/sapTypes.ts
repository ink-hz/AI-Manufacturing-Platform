export type SapSource = {
  system: string;
  environment: string;
  system_id: string;
  client: string;
  namespace: string;
  origin: "native";
  fact_role: "observation";
};
export type SapStatus = {
  configured: boolean;
  source: SapSource | null;
  can_refresh: boolean;
  refresh_error?: { code: string; message: string } | null;
};
export type SapObservation<T> = {
  snapshot: null | {
    id: string;
    kind: "production-order" | "stock-requirements";
    scope: { number?: string; material?: string; plant: string };
    source: SapSource;
    collected_at: string;
    data: T;
    request_id?: string;
  };
  refresh_error: null | { code: string; message: string };
};
export type SapComponent = {
  component_key: string;
  material: string;
  plant: string;
  storage_location: string;
  required_quantity: string;
  withdrawn_quantity: string;
  unit: string;
  required_at: string;
};
export type SapOrder = {
  number: string;
  plant: string;
  material: string;
  description: string;
  quantity: string;
  unit: string;
  components: SapComponent[];
  total: number;
};
export type SapMrp = {
  mrp_list: Record<string, string>;
  items: Record<string, string>[];
  return?: Record<string, string>;
};
