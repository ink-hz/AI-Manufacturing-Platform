import type { SourceRef } from './types';
export type MaterialHandoffFilter = 'pending' | 'disputed' | 'all';
export type MaterialHandoffCommand =
 | {action:'material_handoff.record';material_lot_id:string;work_order_id:string|null;quantity:string;unit:string;from_location:string;to_location:string;receiver_id:string;occurred_at:string|null;note:string|null}
 | {action:'material_handoff.receive';handoff_id:string;received_quantity:string;received_location:string;occurred_at:string|null;note:string|null}
 | {action:'material_handoff.resolve';handoff_id:string;resolution:string}
 | {action:'material_handoff.cancel';handoff_id:string;reason:string};
export interface MaterialHandoffValue {
 kind:'material_handoff';id:string;state:'pending'|'received'|'disputed'|'resolved'|'cancelled';material_lot_id:string;work_order_id:string|null;handoff_number:string;quantity:string;unit:string;from_location:string;to_location:string;sender_id:string;sender_name:string;receiver_id:string;receiver_name:string;occurred_at:string;recorded_at:string;note:string|null;source:SourceRef;
 receipt:{received_quantity:string;received_location:string;note:string|null;actor_id:string;actor_name:string;occurred_at:string;recorded_at:string}|null;
 resolution:{resolution:string;actor_id:string;actor_name:string;recorded_at:string}|null;
 cancellation:{reason:string;actor_id:string;actor_name:string;recorded_at:string}|null;
}
