export interface MaterialRequirement {
 id:string; work_order_id:string; material_id:string; owner_id:string; unit:string;
 required:string; received:string; qualified:string; rejected:string; reserved:string; shortage:string; in_transit:string;
 need_at:string|null; need_at_basis:string; coverage_issues:string[]; expedite_ids:string[]; receipt_ids:string[]; handoff_ids:string[];
}
export interface MaterialProject {
 project_id:string; project_version:number; read_at:string; coverage_issues:string[]; source_modes:string[];
 work_orders:{id:string;title:string}[]; requirements:MaterialRequirement[];
 expedites:{id:string;requirement_id:string;expedite_number:string;state:string;reason:string;impact:string;progress:{note:string}[]}[];
 receipts:{id:string;quantity:string;unit:string;qualified:string;rejected:string;uninspected:string}[];
 handoffs:{id:string;handoff_number:string;material_lot_id:string;work_order_id:string|null;receiver_id:string;quantity:string;unit:string;from_location:string;to_location:string;receiver_name:string;receipt:{received_quantity:string;received_location:string}|null}[]; material_task_counts:Record<string,number>;
 total:number; limit:number; offset:number;
}
export interface MaterialOverview {items:{project_id:string;name:string;product:string;requirement_count:number;open_expedite_count:number;unreceived_handoff_count:number;open_material_task_count:number}[];total:number;limit:number;offset:number;read_at:string}
