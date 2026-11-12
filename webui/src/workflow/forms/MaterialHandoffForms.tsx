import { useEffect, useRef, useState } from 'react';
import type { Grant, MaterialHandoffCommand, MaterialHandoffValue, ObjectSummary, WorkspaceProps } from '../types';
import { Choice, CommandForm, Field, ObjectChoice } from './shared';
import { label } from '../labels';
import { ReceiptUseFields } from './ReceiptUseFields';

type Props = WorkspaceProps & {
  action: MaterialHandoffCommand['action'];
  lots: ObjectSummary[];
  workOrders: ObjectSummary[];
  members: Grant[];
  selected?: MaterialHandoffValue | null;
  onMaterialChanged?: WorkspaceProps["onChanged"];
  currentUserId?: string;
  onMaterialSaved?: () => void;
};
const decimal = (value: string) => value.replace(/^0+(?=\d)/, '')
  .replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
const quantity = (value: string, positive = false) =>
  /^\d+(\.\d+)?$/.test(value) && (!positive || /[1-9]/.test(value));

function BusinessTime({value, onChange}: {value: string | null; onChange(value: string | null): void}) {
  const [local, setLocal] = useState(value ? value.slice(0, 16) : '');
  return <Field name="发生时间" required={false} type="datetime-local" value={local} onChange={next => {
    setLocal(next);
    onChange(next ? new Date(next).toISOString() : null);
  }}/>;
}

export function MaterialHandoffForms(p: Props) {
  const selection = useRef(0);
  const [lookupError, setLookupError] = useState('');
  const [receiptUseReady, setReceiptUseReady] = useState(false);
  const [formVersion] = useState(p.project.version);
  const staleReceipt = formVersion !== p.project.version;
  useEffect(() => () => { selection.current++; }, [p.project.id]);

  if (p.action === 'material_handoff.record') {
    return <CommandForm<Extract<MaterialHandoffCommand, {action: 'material_handoff.record'}>>
      {...p} title="发起物料交接" save="保存交接"
      initial={() => ({
        action: 'material_handoff.record', material_lot_id: '', work_order_id: null,
        quantity: '', unit: '', from_location: '', to_location: '', receiver_id: '', occurred_at: null, note: null,
      })}
      canSubmit={value => !!value.material_lot_id && !!value.unit && quantity(value.quantity, true) &&
        !!value.from_location.trim() && !!value.to_location.trim() &&
        value.from_location.trim() !== value.to_location.trim() &&
        p.members.some(member => member.user_id === value.receiver_id)}>
      {(value, set) => <>
        <ObjectChoice name="物料批次" value={value.material_lot_id} items={p.lots} onChange={id => {
          const request = ++selection.current;
          const unit = p.lots.find(lot => lot.id === id)?.unit || '';
          setLookupError('');
          set({...value, material_lot_id: id, unit});
          if (id && !unit) {
            void p.api.object(p.project.id, 'material_lot', id).then(detail => {
              if (request !== selection.current) return;
              if (detail.value.kind !== 'material_lot') throw Error('批次类型不匹配');
              const unit = detail.value.unit;
              set(current => current.material_lot_id === id ? {...current, unit} : current);
            }).catch(error => {
              if (request === selection.current) setLookupError(String(error));
            });
          }
        }}/>
        {lookupError && <p role="alert">{lookupError} · 请重新选择物料批次。</p>}
        <Field name="交接数量" value={value.quantity} onChange={quantity => set({...value, quantity})}/>
        <p>单位：{value.unit || '选择批次后显示'}</p>
        <Field name="交出位置" value={value.from_location} onChange={from_location => set({...value, from_location})}/>
        <Field name="送达位置" value={value.to_location} onChange={to_location => set({...value, to_location})}/>
        <Choice name="接收人" value={value.receiver_id} choices={{
          '': '请选择',
          ...Object.fromEntries(p.members.map(member => [member.user_id, member.display_name || member.user_id])),
        }} onChange={receiver_id => set({...value, receiver_id})}/>
        <details>
          <summary>补充信息</summary>
          <ObjectChoice name="关联工单" required={false} value={value.work_order_id || ''} items={p.workOrders}
            onChange={id => set({...value, work_order_id: id || null})}/>
          <BusinessTime value={value.occurred_at} onChange={occurred_at => set({...value, occurred_at})}/>
          <Field name="备注" required={false} value={value.note || ''} onChange={note => set({...value, note: note || null})}/>
        </details>
      </>}
    </CommandForm>;
  }

  const handoff = p.selected;
  if (!handoff) return <p>请选择有权办理的交接记录。</p>;
  if (p.action === 'material_handoff.receive') {
    return <CommandForm<Extract<MaterialHandoffCommand, {action: 'material_handoff.receive'}>>
      {...p} onAcknowledged={p.onMaterialChanged} onSaved={p.onMaterialSaved} identity={p.currentUserId} title="确认接收" save="确认接收"
      initial={() => ({
        action: 'material_handoff.receive', handoff_id: handoff.id,
        received_quantity: handoff.quantity, received_location: handoff.to_location, occurred_at: null, note: null,
        receipt_use: 'unspecified', requirement_id: null,
      })}
      canSubmit={value => !staleReceipt && quantity(value.received_quantity) && !!value.received_location.trim() &&
        (value.receipt_use !== 'line_side' || (!!value.requirement_id && receiptUseReady)) &&
        ((decimal(value.received_quantity) === decimal(handoff.quantity) &&
          value.received_location.trim() === handoff.to_location) || !!value.note?.trim())}>
      {(value, set) => {
        const differs = decimal(value.received_quantity) !== decimal(handoff.quantity) ||
          value.received_location.trim() !== handoff.to_location;
        return <>
          {staleReceipt && <p>项目已更新，草稿已保留；请重新打开收料操作。</p>}
          <p>{handoff.handoff_number} · 交出 {handoff.quantity} {handoff.unit} · {handoff.from_location} → {handoff.to_location}（送达位置待接收确认） · 接收人 {handoff.receiver_name}</p>
          <Field name="实收数量" value={value.received_quantity}
            onChange={received_quantity => set({...value, received_quantity})}/>
          <p>单位：{handoff.unit}</p>
          <Field name="实际接收位置" value={value.received_location}
            onChange={received_location => set({...value, received_location})}/>
          <ReceiptUseFields api={p.api} projectId={p.project.id} projectVersion={p.project.version} handoff={handoff}
            value={{receipt_use:value.receipt_use || 'unspecified',requirement_id:value.requirement_id || null}}
            onReady={setReceiptUseReady} disabled={p.readOnly}
            onChange={scope => set({...value,...scope})}/>
          {differs && <Field name="差异说明" value={value.note || ''} onChange={note => set({...value, note: note || null})}/>}
          <details>
            <summary>补充信息</summary>
            <BusinessTime value={value.occurred_at} onChange={occurred_at => set({...value, occurred_at})}/>
            {!differs && <Field name="备注" required={false} value={value.note || ''}
              onChange={note => set({...value, note: note || null})}/>}
          </details>
        </>;
      }}
    </CommandForm>;
  }

  if (p.action === 'material_handoff.confirm_use') {
    return <CommandForm<Extract<MaterialHandoffCommand, {action: 'material_handoff.confirm_use'}>>
      {...p} onAcknowledged={p.onMaterialChanged} onSaved={p.onMaterialSaved} identity={p.currentUserId} title="核对实收用途" save="保存实收用途"
      initial={() => ({action:'material_handoff.confirm_use',handoff_id:handoff.id,
        receipt_use:'transfer',requirement_id:null,evidence:''})}
      canSubmit={value => !staleReceipt && !!value.evidence.trim() && (value.receipt_use !== 'line_side' || (!!value.requirement_id && receiptUseReady))}>
      {(value,set) => <>
        {staleReceipt && <p>项目已更新，草稿已保留；请重新打开用途核对。</p>}
        <p>{handoff.handoff_number} · 已签收 {handoff.receipt?.received_quantity} {handoff.unit} · {handoff.receipt?.received_location}</p>
        <ReceiptUseFields api={p.api} projectId={p.project.id} projectVersion={p.project.version} handoff={handoff} value={value}
          allowUnspecified={false} disabled={p.readOnly} onReady={setReceiptUseReady}
          onChange={scope => set({...value,receipt_use:scope.receipt_use === 'line_side' ? 'line_side' : 'transfer',requirement_id:scope.requirement_id})}/>
        <Field name="用途核对说明" value={value.evidence} onChange={evidence => set({...value,evidence})}/>
      </>}
    </CommandForm>;
  }

  if (p.action === 'material_handoff.resolve') {
    return <CommandForm<Extract<MaterialHandoffCommand, {action: 'material_handoff.resolve'}>>
      {...p} title={label(p.action)} save="保存差异处理"
      initial={() => ({action: 'material_handoff.resolve', handoff_id: handoff.id, resolution: ''})}
      canSubmit={value => !!value.resolution.trim()}>
      {(value, set) => <>
        <p>{handoff.handoff_number} · 交出 {handoff.quantity} {handoff.unit} · 实收 {handoff.receipt?.received_quantity} {handoff.unit} · {handoff.receipt?.received_location} · {handoff.receipt?.note}</p>
        <Field name="处理说明" value={value.resolution} onChange={resolution => set({...value, resolution})}/>
      </>}
    </CommandForm>;
  }
  return <CommandForm<Extract<MaterialHandoffCommand, {action: 'material_handoff.cancel'}>>
    {...p} title="取消交接" save="确认取消交接"
    initial={() => ({action: 'material_handoff.cancel', handoff_id: handoff.id, reason: ''})}
    canSubmit={value => !!value.reason.trim()}>
    {(value, set) => <>
      <p>{handoff.handoff_number} · {handoff.quantity} {handoff.unit} · {handoff.from_location} → {handoff.to_location}</p>
      <Field name="取消原因" value={value.reason} onChange={reason => set({...value, reason})}/>
    </>}
  </CommandForm>;
}
