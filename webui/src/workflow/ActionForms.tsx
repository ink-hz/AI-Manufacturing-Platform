import { useState } from 'react';
import { label } from './labels';
import type { CommandFields, WorkspaceProps, ObjectDetail } from './types';
import { Choice, CommandForm, Field } from './forms/shared';
export function ActionForms(p: WorkspaceProps & {
    detail?: ObjectDetail | null;
    onChoose?(action: string): void;
}) {
    const [open, setOpen] = useState(false);
    if (p.detail)
        return <section aria-label="当前对象可用动作"><h4>当前对象可用动作</h4>{p.detail.summary.action_capabilities?.flatMap(c => Object.entries(c.variants).map(([variant, state]) => <p key={c.action + variant}>{label(c.action)} · {label(variant)} · {state.ready === true ? "当前条件满足" : state.ready === false ? "当前受阻" : "选择具体范围后核验"} {state.blocking_reasons.join("；")}</p>))}{p.detail.summary.blocking_reasons.map(r => <p key={r}>{p.detail!.summary.kind === "material_handoff" ? label(r) : r}</p>)}{!p.readOnly && p.detail.summary.next_actions.filter(a => p.project.allowed_actions.includes(a as CommandFields['action'])).map(a => <button key={a} onClick={() => p.onChoose?.(a)}>前往处理：{label(a)}</button>)}</section>;
    if (p.readOnly || !p.project.allowed_actions.includes('project.stage'))
        return null;
    return <details onToggle={e => { if (e.currentTarget.open)
        setOpen(true); }}><summary>协作阶段提示</summary><p>阶段提示用于协作沟通；实际交付、质量与成本按业务事实独立判断。</p>{p.project.stages.map(s => <p key={s.stage}>{s.stage} · {s.status} · {s.reason}</p>)}{open && <CommandForm<Extract<CommandFields, {
            action: 'project.stage';
        }>> {...p} title="更新协作阶段提示" save="保存阶段提示" initial={() => ({ action: 'project.stage', stage: 'S1', status: 'active', reason: '' })}>{(v, set) => <><Choice name="协作阶段" value={v.stage} choices={Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`S${i + 1}`, `S${i + 1}`]))} onChange={x => set({ ...v, stage: x as typeof v.stage })}/><Choice name="协作状态" value={v.status} choices={{ pending: '待开始', active: '进行中', blocked: '有阻断', complete: '协作完成' }} onChange={x => set({ ...v, status: x as typeof v.status })}/><Field name="阶段说明" value={v.reason} onChange={x => set({ ...v, reason: x })}/></>}</CommandForm>}</details>;
}
