import type { ObjectDetail, WorkflowTarget } from '../types';

export function MaterialHandoffDetails({data, onOpen}: {
  data: ObjectDetail;
  onOpen(target: WorkflowTarget): void;
}) {
  const handoff = data.value;
  if (handoff.kind !== 'material_handoff') return null;
  return <section aria-label="物料交接事实">
    <p>交接编号 {handoff.handoff_number} · 人工登记</p>
    <p>本笔交接 {handoff.quantity} {handoff.unit}；同批次其他交接分别记录，不代表整批库存或唯一位置。</p>
    <button onClick={() => onOpen({projectId: data.summary.project_id, kind: 'material_lot', id: handoff.material_lot_id})}>
      查看物料批次
    </button>
    {handoff.work_order_id && <button onClick={() => onOpen({projectId: data.summary.project_id, kind: 'work_order', id: handoff.work_order_id!})}>
      查看关联工单
    </button>}
    <dl className="wf-facts">
      <div><dt>交出位置</dt><dd>{handoff.from_location}</dd></div>
      <div><dt>送达位置</dt><dd>{handoff.to_location}（{handoff.receipt ? '原计划送达位置' : '尚未接收确认'}）</dd></div>
      <div><dt>交出人</dt><dd>{handoff.sender_name}</dd></div>
      <div><dt>接收人</dt><dd>{handoff.receiver_name}</dd></div>
      <div><dt>交接发生时间</dt><dd>{handoff.occurred_at}</dd></div>
    </dl>
    {handoff.note && <p>备注：{handoff.note}</p>}
    {handoff.receipt && <section>
      <h4>接收事实</h4>
      <p>实收 {handoff.receipt.received_quantity} {handoff.unit} · 实际接收位置 {handoff.receipt.received_location}</p>
      <p>{handoff.receipt.actor_name} · {handoff.receipt.occurred_at}</p>
      {handoff.receipt.note && <p>接收说明：{handoff.receipt.note}</p>}
    </section>}
    {handoff.resolution && <section>
      <h4>差异处理</h4>
      <p>{handoff.resolution.resolution} · {handoff.resolution.actor_name} · {handoff.resolution.recorded_at}</p>
    </section>}
    {handoff.cancellation && <section>
      <h4>取消记录</h4>
      <p>{handoff.cancellation.reason} · {handoff.cancellation.actor_name} · {handoff.cancellation.recorded_at}</p>
    </section>}
    {!!data.summary.blocking_reasons.length && <details className="wf-evidence-details">
      <summary>责任核验依据</summary>
      {data.summary.blocking_reasons.map(reason => <p key={reason}>{reason}</p>)}
    </details>}
  </section>;
}
