import type { ObjectDetail, WorkflowTarget } from '../types';
export function MaterialHandoffDetails({data,onOpen}:{data:ObjectDetail;onOpen(t:WorkflowTarget):void}){
 const h=data.value;if(h.kind!=='material_handoff')return null;
 return <section aria-label="物料交接事实"><p>交接编号 {h.handoff_number} · 人工登记</p><p>本笔交接 {h.quantity} {h.unit}；同批次其他交接分别记录，不代表整批库存或唯一位置。</p><button onClick={()=>onOpen({projectId:data.summary.project_id,kind:'material_lot',id:h.material_lot_id})}>查看物料批次</button>{h.work_order_id&&<button onClick={()=>onOpen({projectId:data.summary.project_id,kind:'work_order',id:h.work_order_id!})}>查看关联工单</button>}<dl className="wf-facts"><div><dt>交出位置</dt><dd>{h.from_location}</dd></div><div><dt>送达位置</dt><dd>{h.to_location}（{h.receipt?'原计划送达位置':'尚未接收确认'}）</dd></div><div><dt>交出人</dt><dd>{h.sender_name}</dd></div><div><dt>接收人</dt><dd>{h.receiver_name}</dd></div><div><dt>交接发生时间</dt><dd>{h.occurred_at}</dd></div></dl>{h.note&&<p>备注：{h.note}</p>}
 {h.receipt&&<section><h4>接收事实</h4><p>实收 {h.receipt.received_quantity} {h.unit} · 实际接收位置 {h.receipt.received_location}</p><p>{h.receipt.actor_name} · {h.receipt.occurred_at}</p>{h.receipt.note&&<p>接收说明：{h.receipt.note}</p>}</section>}
 {h.resolution&&<section><h4>差异处理</h4><p>{h.resolution.resolution} · {h.resolution.actor_name} · {h.resolution.recorded_at}</p></section>}
 {h.cancellation&&<section><h4>取消记录</h4><p>{h.cancellation.reason} · {h.cancellation.actor_name} · {h.cancellation.recorded_at}</p></section>}
 </section>;
}
