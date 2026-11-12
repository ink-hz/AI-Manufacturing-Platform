import type { HandoffRow } from './materialHandoffHydration';
import type { ObjectDetail, ProjectDetail, WorkflowTarget } from './types';
import { StatusBadge } from './StatusBadge';
import { label } from './labels';

export function MaterialHandoffTable({rows, projects, onOpen, onRetry, onAction, allowedActions, retryDisabled}: {
  rows: HandoffRow[];
  projects?: ProjectDetail[];
  onOpen(target: WorkflowTarget): void;
  onRetry(row: HandoffRow): void;
  retryDisabled?: boolean;
  allowedActions?: readonly string[];
  onAction?(action: string, detail: ObjectDetail): void;
}) {
  return <div className="wf-table-scroll"><table>
    <thead><tr>
      <th>交接记录</th>{projects && <th>所属项目</th>}<th>物料批次</th>
      <th>数量</th><th>位置</th><th>交出人 / 接收人</th><th>状态</th><th>办理 / 读取状态</th>
    </tr></thead>
    <tbody>{rows.map(row => {
      const {summary, detail} = row;
      const h = detail?.value.kind === 'material_handoff' ? detail.value : null;
      return <tr key={summary.project_id + summary.id}>
        <td><button className="wf-text-link" onClick={() => onOpen({projectId: summary.project_id, kind: 'material_handoff', id: summary.id})}>
          {h?.handoff_number || summary.title}
        </button><p>人工登记</p></td>
        {projects && <td>{projects.find(p => p.id === summary.project_id)?.name || summary.project_id}</td>}
        <td>{h ? <button onClick={() => onOpen({projectId: summary.project_id, kind: 'material_lot', id: h.material_lot_id})}>
          {row.batch || (row.batchError ? '批次信息未读取' : '正在读取批次…')}
        </button> : '未读取'}</td>
        <td>{h ? <>{h.quantity} {h.unit}{h.receipt && <><p>实收 {h.receipt.received_quantity} {h.unit}</p><p>{h.receipt.receipt_use === 'line_side' ? '线边实收' : h.receipt.receipt_use === 'transfer' ? '中转接收' : '实收用途未核对'}</p></>}</> : '未读取'}</td>
        <td>{h ? <>{h.from_location} → {h.to_location}{h.receipt
          ? <p>实际接收：{h.receipt.received_location}</p>
          : h.state === 'pending' ? '（送达位置待接收确认）' : '（未确认接收）'}</> : '未读取'}</td>
        <td>{h ? `${h.sender_name} / ${h.receiver_name}` : '未读取'}</td>
        <td><StatusBadge state={h?.state || summary.state} kind="material_handoff"/></td>
        <td>{row.loading ? <span>正在读取…</span> : (row.error || row.batchError) ? <>
          <p role="alert">{row.error ? '交接详情未读取' : '批次信息未读取'}：{row.error || row.batchError}</p>
          <button disabled={retryDisabled} onClick={() => onRetry(row)}>重试此行</button>
        </> : null}
          {h && detail && onAction && detail.summary.next_actions.filter(a => a.startsWith("material_handoff.") && allowedActions?.includes(a)).map(action =>
            <button key={action} onClick={() => onAction(action, detail)}>{label(action)}</button>)}
        </td>
      </tr>;
    })}</tbody>
  </table></div>;
}
