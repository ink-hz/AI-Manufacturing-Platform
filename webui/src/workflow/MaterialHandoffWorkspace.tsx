import { useEffect, useRef, useState } from 'react';
import type { OEMWorkspaceProps } from './OEMWorkspace';
import type { Grant, MaterialHandoffCommand, ObjectDetail, ObjectKind, ObjectSummary } from './types';
import { MaterialHandoffForms } from './forms/MaterialHandoffForms';
import { MaterialHandoffTable } from './MaterialHandoffTable';
import { hydrateHandoffPage, type HandoffRow } from './materialHandoffHydration';
import { label } from './labels';

const kinds: ObjectKind[] = ['material_handoff', 'material_lot', 'work_order'];
const eligible = (m: Grant) => m.active && m.roles.some(r =>
  ['warehouse', 'supply', 'production', 'project_owner'].includes(r));
type HandoffAction = MaterialHandoffCommand['action'];

export function MaterialHandoffWorkspace(p: OEMWorkspaceProps & {currentUserId?: string}) {
  const [items, setItems] = useState<Partial<Record<ObjectKind, ObjectSummary[]>>>({});
  const [totals, setTotals] = useState<Partial<Record<ObjectKind, number>>>({});
  const [rows, setRows] = useState<HandoffRow[]>([]);
  const [members, setMembers] = useState<Grant[]>([]);
  const [memberOffset, setMemberOffset] = useState(0);
  const [hasMembers, setHasMembers] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [filter, setFilter] = useState('pending');
  const [action, setAction] = useState<HandoffAction | null>(
    p.initialAction?.startsWith('material_handoff.') ? p.initialAction as HandoffAction : null);
  const [epoch, setEpoch] = useState(0);
  const [chosen, setChosen] = useState<ObjectDetail | null>(null);
  const generation = useRef(0);
  const requests = useRef<AbortController | null>(null);

  useEffect(() => {
    if (p.onSelectAction) setAction(p.initialAction?.startsWith('material_handoff.')
      ? p.initialAction as HandoffAction : null);
  }, [p.initialAction, p.onSelectAction]);

  function updateRow(row: HandoffRow) {
    setRows(old => old.map(current => current.summary.id === row.summary.id ? row : current));
  }
  function appendError(message: string) {
    setError(old => old ? `${old}；${message}` : message);
  }
  useEffect(() => {
    const controller = new AbortController(), current = ++generation.current;
    requests.current = controller;
    const active = () => !controller.signal.aborted && current === generation.current;
    setItems({}); setTotals({}); setRows([]); setMembers([]);
    setMemberOffset(0); setHasMembers(false); setError(''); setBusy(true);

    // Choice lists and handoff rows fail independently. A missing work-order
    // option must not erase readable handoffs or already loaded member choices.
    const pages = kinds.map(async kind => {
      try {
        const page = await p.api.objects(p.project.id, kind, 50, 0, controller.signal);
        if (!active()) return;
        setItems(old => ({...old, [kind]: page.items}));
        setTotals(old => ({...old, [kind]: page.total}));
        if (kind === 'material_handoff') {
          setRows(page.items.map(summary => ({summary, loading: true})));
          await hydrateHandoffPage(p.api, page.items, controller.signal, row => {
            if (active()) updateRow(row);
          });
        }
      } catch (e) { if (active()) appendError(`${label(kind)}：${String(e)}`); }
    });
    const directory = p.api.members(p.project.id, 50, 0).then(page => {
      if (!active()) return;
      setMembers(page.items); setMemberOffset(page.items.length);
      setHasMembers(page.items.length === 50);
    }).catch(e => { if (active()) appendError(`项目成员：${String(e)}`); });
    void Promise.all([...pages, directory]).finally(() => { if (active()) setBusy(false); });
    return () => { generation.current++; controller.abort(); };
  }, [p.api, p.project.id, p.project.version, retry]);

  async function more(kind: ObjectKind | 'members') {
    if (busy) return;
    const current = generation.current, controller = requests.current;
    if (!controller || controller.signal.aborted) return;
    const active = () => current === generation.current && !controller.signal.aborted;
    setBusy(true); setError('');
    try {
      if (kind === 'members') {
        const page = await p.api.members(p.project.id, 50, memberOffset);
        if (!active()) return;
        setMembers(old => [...old, ...page.items]);
        setMemberOffset(old => old + page.items.length); setHasMembers(page.items.length === 50);
      } else {
        const page = await p.api.objects(p.project.id, kind, 50, (items[kind] || []).length, controller.signal);
        if (!active()) return;
        setItems(old => ({...old, [kind]: [...(old[kind] || []), ...page.items]}));
        setTotals(old => ({...old, [kind]: page.total}));
        if (kind === 'material_handoff') {
          setRows(old => [...old, ...page.items.map(summary => ({summary, loading: true}))]);
          await hydrateHandoffPage(p.api, page.items, controller.signal, row => {
            if (active()) updateRow(row);
          });
        }
      }
    } catch (e) { if (active()) setError(String(e)); }
    finally { if (active()) setBusy(false); }
  }

  function retryRow(row: HandoffRow) {
    const controller = requests.current;
    if (!controller || controller.signal.aborted) return;
    updateRow({...row, loading: true, error: undefined, batchError: undefined});
    void hydrateHandoffPage(p.api, [row.summary], controller.signal, next => {
      if (!controller.signal.aborted) updateRow(next);
    }).catch(e => { if (!controller.signal.aborted) appendError(String(e)); });
  }
  const scoped = p.initialObject?.summary.project_id === p.project.id &&
    p.initialObject.value.kind === 'material_handoff' ? p.initialObject : null;
  const selected = chosen?.summary.project_id === p.project.id ? chosen : scoped;
  const permitted = !!action && p.project.allowed_actions.includes(action) && !p.readOnly &&
    (action === 'material_handoff.record' || !!selected?.summary.next_actions.includes(action));
  const visibleRows = rows.filter(row => filter === 'all' ||
    (row.detail?.summary.state || row.summary.state) === filter);

  function choose(next: HandoffAction, detail: ObjectDetail | null = null) {
    p.requestLeave(() => {
      p.onSelectAction?.(next); setChosen(detail); setAction(next); setEpoch(old => old + 1);
    });
  }
  function discard() {
    p.requestLeave(() => {
      setAction(null); setChosen(null); p.onSelectAction?.(null); setRetry(old => old + 1);
    });
  }
  return <section aria-label="物料交接工作区">
    <h3>物料交接</h3>
    <p>人工登记 · 每笔交接分别确认数量与位置；同批次拆分记录不代表整批物料位置。待接收的送达位置尚未确认。</p>
    {!p.readOnly && p.project.allowed_actions.includes('material_handoff.record') &&
      <button onClick={() => choose('material_handoff.record')}>发起物料交接</button>}
    {permitted && <>
      <button onClick={discard}>放弃草稿并重新读取</button>
      <MaterialHandoffForms key={p.project.id + action + selected?.summary.id + epoch} {...p}
        action={action!} selected={selected?.value.kind === 'material_handoff' ? selected.value : null}
        lots={items.material_lot || []} workOrders={items.work_order || []}
        members={members.filter(m => eligible(m) && m.user_id !== p.currentUserId)}
        onChanged={result => { setAction(null); p.onChanged(result); }}/>
      {(['material_lot', 'work_order'] as const).map(kind =>
        (items[kind] || []).length < (totals[kind] || 0) && <button key={kind} disabled={busy} onClick={() => void more(kind)}>
          读取更多{label(kind)}（已读取 {(items[kind] || []).length} / {totals[kind]}）
        </button>)}
      {action === 'material_handoff.record' && hasMembers &&
        <button disabled={busy} onClick={() => void more('members')}>读取更多项目成员（已读取 {memberOffset}）</button>}
    </>}
    {error && <p role="alert">{error}<button onClick={() => setRetry(old => old + 1)}>重试读取交接</button></p>}
    <div className="mf-tabs" aria-label="交接状态筛选">
      {([['pending', '待接收'], ['disputed', '待处理差异'], ['all', '全部记录']] as const).map(([value, title]) =>
        <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{title}</button>)}
    </div>
    <p role="status">已读取 {(items.material_handoff || []).length} / {totals.material_handoff || 0} · 仅筛选已读取记录 · 当前显示 {visibleRows.length} 条{busy ? ' · 正在读取…' : ''}</p>
    <MaterialHandoffTable rows={visibleRows} onOpen={p.onOpen} onRetry={retryRow} retryDisabled={busy || rows.some(row => row.loading)}
      allowedActions={p.readOnly ? [] : p.project.allowed_actions}
      onAction={(next, detail) => choose(next as HandoffAction, detail)}/>
    {(items.material_handoff || []).length < (totals.material_handoff || 0) &&
      <button disabled={busy} onClick={() => void more('material_handoff')}>读取更多交接记录</button>}
  </section>;
}
