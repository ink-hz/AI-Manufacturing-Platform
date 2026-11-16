import { useEffect, useRef, useState } from 'react';
import type { WorkflowApi } from '../api';
import type { MesKind, MesObservation, MesScope, MesStatus, MesSource, MesOrder } from './types';
const known = (v: unknown) => v === undefined || v === null || v === '' ? '未知' : String(v);
const identity = (s: MesSource) => JSON.stringify([s.namespace, s.environment, s.site_code, s.system, s.origin, s.fact_role]);
function useObservation(api: WorkflowApi, status: MesStatus | null, kind: MesKind, scope: MesScope, accountId: string, readOnly: boolean) {
    const key = JSON.stringify([kind, scope, accountId, status?.source, readOnly]);
    const [state, setState] = useState<{
        key: string;
        api: WorkflowApi;
        value: MesObservation | null;
        busy: boolean;
        failed: boolean;
    } | null>(null);
    const [attempt, setAttempt] = useState(0);
    const manual = useRef(false);
    useEffect(() => {
        if (!status?.configured || status.refresh_error || !status.source)
            return;
        let live = true;
        const c = new AbortController();
        const expected = status.source;
        const refresh = manual.current;
        manual.current = false;
        setState(old => ({ key, api, value: old?.key === key && old.api === api ? old.value : null, busy: true, failed: false }));
        const accept = (v: MesObservation) => {
            if (v.snapshot && (identity(v.snapshot.source) !== identity(expected) || JSON.stringify(v.snapshot.scope) !== JSON.stringify(scope))) {
                // Scope object property order is not a business identity.
                if (identity(v.snapshot.source) !== identity(expected) || Object.entries(scope).some(([k, x]) => v.snapshot!.scope[k] !== x) || Object.keys(v.snapshot.scope).length !== Object.keys(scope).length)
                    throw Error('scope');
            }
            return v;
        };
        void (async () => {
            try {
                let value = accept(await api.mesSourceQuery(kind, scope, refresh, c.signal));
                if (!live)
                    return;
                if (!refresh && !value.snapshot && !value.refresh_error && status.can_refresh && !readOnly)
                    value = accept(await api.mesSourceQuery(kind, scope, true, c.signal));
                if (live)
                    setState({ key, api, value, busy: false, failed: false });
            }
            catch {
                if (live)
                    setState(old => ({ key, api, value: old?.key === key && old.api === api ? old.value : null, busy: false, failed: true }));
            }
        })();
        return () => { live = false; c.abort(); };
    }, [api, key, attempt]);
    const current = state?.key === key && state.api === api ? state : null;
    return { value: current?.value, busy: current?.busy, failed: current?.failed, refresh: () => { manual.current = true; setAttempt(x => x + 1); } };
}
function Result({ query, children }: {
    query: ReturnType<typeof useObservation>;
    children: (data: NonNullable<MesObservation['snapshot']>['data']) => React.ReactNode;
}) {
    const value = query.value;
    const snapshot = value?.snapshot;
    return <>{query.busy && <p role="status">正在读取…</p>}{(query.failed || value?.refresh_error) && <p role="alert">读取失败：{value?.refresh_error?.code === 'MES_RELAY_UNAVAILABLE' ? '只读连接器离线。' : '请核对连接或权限后重试；组件超过上限时不展示未取全结果。'}{snapshot && ' 保留上次成功结果及原读取时间。'}</p>}{snapshot ? <><p>读取时间 {snapshot.collected_at}</p>{children(snapshot.data)}</> : !query.busy && !query.failed && !value?.refresh_error && <p>尚未查询，无已保存结果。</p>}</>;
}
function MaterialRecords({ api, status, accountId, readOnly, order, material }: {
    api: WorkflowApi;
    status: MesStatus;
    accountId: string;
    readOnly: boolean;
    order: string;
    material: string;
}) {
    const [priorityPage, setPriorityPage] = useState(1), [iqcPage, setIqcPage] = useState(1);
    const priority = useObservation(api, status, 'priority', { shop_order: order, material, page: priorityPage }, accountId, readOnly);
    const iqc = useObservation(api, status, 'iqc', { material, page: iqcPage }, accountId, readOnly);
    return <>{([{ title: '源优先级与缺口', query: priority, page: priorityPage, setPage: setPriorityPage, fields: [['SHOP_ORDER', '工单'], ['MATNR', '物料'], ['MAKTX', '说明'], ['MEINS', '单位'], ['ITEM_GRADE', '优先级'], ['DFQTY', '缺口'], ['INVQTY', '库存'], ['WINVQTY', '在途'], ['ORDER_PLAN_DATE', '计划日期'], ['SALE_DATE', '销售日期']] }, { title: '相关IQC', query: iqc, page: iqcPage, setPage: setIqcPage, fields: [['ITEM_NO', '物料'], ['INSP_CODE', '检验单'], ['RESULT', '结果'], ['STATUS', '状态'], ['INSP_QTY', '检验量'], ['NG_QTY', '不良量'], ['RQ', '日期'], ['JYDATE', '检验日期']] }]).map(({ title, query, page, setPage, fields }) => <section key={title}><h4>{title}</h4>{title === '相关IQC' && <p>仅为该物料的相关检验记录，未关联本工单或批次，不计入本工单合格可用量。</p>}<button disabled={query.busy || readOnly || !status.can_refresh} onClick={query.refresh}>刷新{title}</button><Result query={query}>{data => <>{!data.rows?.length ? <p>本页无记录。</p> : <div style={{ overflow: 'auto' }}><table><thead><tr>{fields.map(([k, label]) => <th key={k}>{label}</th>)}</tr></thead><tbody>{data.rows.map((row, i) => <tr key={i}>{fields.map(([k]) => <td key={k}>{known(row[k])}</td>)}</tr>)}</tbody></table></div>}<p>第 {page} 页 · 共 {known(data.total_items)} 条</p><button disabled={page === 1 || query.busy} onClick={() => setPage(page - 1)}>上一页{title}</button><button disabled={query.busy || data.total_items === undefined || page * 5 >= data.total_items} onClick={() => setPage(page + 1)}>下一页{title}</button></>}</Result></section>)}</>;
}
export function MesSourceWorkbench({ api, readOnly, accountId, selectedOrder, onSelectOrder }: {
    api: WorkflowApi;
    readOnly: boolean;
    accountId: string;
    selectedOrder?: MesOrder | null;
    onSelectOrder?: (order: MesOrder | null) => void;
}) {
    const [status, setStatus] = useState<{
        api: WorkflowApi;
        account: string;
        value: MesStatus;
    } | null>(null), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0);
    const [draft, setDraft] = useState(''), [prefix, setPrefix] = useState(''), [cursors, setCursors] = useState(['']), [localOrder, setLocalOrder] = useState<MesOrder | null>(null), [material, setMaterial] = useState('');
    const order = selectedOrder === undefined ? localOrder : selectedOrder;
    const current = status?.api === api && status.account === accountId ? status.value : null;
    useEffect(() => { let live = true; const c = new AbortController(); setStatus(null); setFailed(false); setMaterial(''); setLocalOrder(null); setPrefix(''); setDraft(''); setCursors(['']); api.mesSourceStatus(c.signal).then(value => { if (live)
        setStatus({ api, account: accountId, value }); }, () => { if (live)
        setFailed(true); }); return () => { live = false; c.abort(); }; }, [api, accountId, retry]);
    const orders = useObservation(api, current, 'orders', { prefix, after: cursors[cursors.length - 1] }, accountId, readOnly);
    const components = useObservation(api, order ? current : null, 'order-materials', { shop_order: order?.shop_order || '' }, accountId, readOnly);
    function select(value: MesOrder | null) { setLocalOrder(value); onSelectOrder?.(value); setMaterial(''); }
    return <section aria-label="MES源工单"><h2>现场源工单</h2>{failed || current?.refresh_error ? <p role="alert">源连接状态读取失败。<button onClick={() => setRetry(x => x + 1)}>重试连接状态</button></p> : !current ? <p>正在读取MES连接状态…</p> : !current.configured ? <p>MES源尚未配置。</p> : <><p>{current.source?.environment === 'production' ? 'MES生产环境' : current.source?.environment === 'test' ? 'MES测试环境' : 'MES环境待核对'} · 站点 {known(current.source?.site_code)} · 只读观察</p><form onSubmit={e => { e.preventDefault(); setPrefix(draft); setCursors(['']); select(null); }}><label>工单前缀<input maxLength={64} value={draft} onChange={e => setDraft(e.target.value)}/></label><button>查询工单</button></form><button disabled={orders.busy || readOnly || !current.can_refresh} onClick={orders.refresh}>刷新工单</button><Result query={orders}>{data => <>{!data.items?.length ? <p>本页无工单。</p> : <table><thead><tr><th>MES工单</th><th>说明</th></tr></thead><tbody>{data.items.map(row => <tr key={row.shop_order}><td><button onClick={() => select(row)}>{row.shop_order}</button></td><td>{known(row.description)}</td></tr>)}</tbody></table>}<p>第 {cursors.length} 页 · 本页 {data.items?.length || 0} 条（总数未知）</p><button disabled={orders.busy || cursors.length === 1} onClick={() => setCursors(x => x.slice(0, -1))}>上一页工单</button><button disabled={orders.busy || !data.next_cursor} onClick={() => setCursors(x => [...x, data.next_cursor!])}>下一页工单</button></>}</Result>{order && <section><h3>工单 {order.shop_order} · {known(order.description)}</h3><p>MES已提量不等于物流领取或线边实收。</p><button disabled={components.busy || readOnly || !current.can_refresh} onClick={components.refresh}>刷新组件</button><Result query={components}>{data => <><p>完整组件 {known(data.total)} 条</p><table><thead><tr><th>物料</th><th>需求量</th><th>已提量</th><th>单位</th><th>相关记录</th></tr></thead><tbody>{data.components?.map(row => <tr key={row.component_key}><td>{row.material_id}</td><td>{known(row.required_quantity)}</td><td>{known(row.withdrawn_quantity)}</td><td>{known(row.unit)}</td><td><button onClick={() => setMaterial(row.material_id)}>查看 {row.material_id}</button></td></tr>)}</tbody></table></>}</Result>{material && <MaterialRecords key={accountId + identity(current.source!) + order.shop_order + material} api={api} status={current} accountId={accountId} readOnly={readOnly} order={order.shop_order} material={material}/>}</section>}</>}</section>;
}
