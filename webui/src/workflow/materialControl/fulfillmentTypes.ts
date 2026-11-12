export interface FulfillmentCheck {
  can_fulfill: boolean;
  project_version: number;
  evaluated_at: string;
  current_requirement_id?: string | null;
  required: string;
  qualified: string | null;
  usable_reserved: string;
  line_received: string | null;
  remaining_to_receive: string | null;
  unit: string;
  blocking_reasons: string[];
}
export interface ExpediteValue {
  kind: "material_expedite";
  id: string;
  requirement_id: string;
  expedite_number: string;
  state: string;
  reason: string;
  impact: string;
  progress: { note: string }[];
  fulfillment_check: FulfillmentCheck | null;
  closure?: { outcome: string; reason: string; fulfillment_proof?: FulfillmentCheck | null } | null;
}
