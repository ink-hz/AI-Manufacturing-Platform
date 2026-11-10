import { useEffect, useRef, useState, type FormEvent } from 'react';
import { WorkflowError, type createWorkflowApi } from '../api';
import type { CatalogKind, ObservationKind, ProductionPage, ProductionRow, ProductionStatus, SourceKind, SourceProject, TimeFilters } from './types';
import './productionTools.css';

type Tab = 'observations' | 'catalog' | 'evidence' | 'statistics';
const tabs: [Tab, string][] = [['observations', 'SN 观测'], ['catalog', '软件与配置目录'], ['evidence', '日志证据'], ['statistics', '记录统计']];
const catalogs: [CatalogKind, string][] = [['software', '软件目录'], ['software_versions', '软件版本'], ['configs', '配置目录'], ['config_versions', '配置版本'], ['review_orders', '工具配置审核单']];
const statistics = [['records', '记录总数'], ['distinct_sn', '非空 SN 数'], ['pass_records', 'PASS 记录'], ['fail_records', 'FAIL 记录'], ['unknown_records', '未知结果记录']] as const;
function localInput(date: Date) { return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
function defaultRange() { const end = new Date(); return {start: localInput(new Date(end.getTime() - 86400000)), end: localInput(end), sn: '', device: '', parent: ''}; }
function text(value: unknown): string { return value === undefined ? '—' : value === null ? 'null' : typeof value === 'object' ? JSON.stringify(value) : String(value); }
function localTime(value: unknown) { const date = new Date(String(value)); return Number.isNaN(date.getTime()) ? text(value) : date.toLocaleString(); }
function evidenceId(row: ProductionRow): string | null {
  const id = typeof row.id === 'string' ? row.id : '';
  return /^[1-9][0-9]{0,19}$/.test(id) ? id : null;
}

export function ProductionToolsWorkspace({api}: {api: ReturnType<typeof createWorkflowApi>}) {
  const [projects, setProjects] = useState<SourceProject[]>([]);
  const [selected, setSelected] = useState('');
  const [globalStatus, setGlobalStatus] = useState<ProductionStatus | null>(null);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [directoryError, setDirectoryError] = useState('');
  const [directoryReady, setDirectoryReady] = useState(false);
  const [directoryBefore, setDirectoryBefore] = useState<string>();
  const [directoryNext, setDirectoryNext] = useState<string | null>(null);
  const [directoryRetry, setDirectoryRetry] = useState(0);
  const directoryGeneration = useRef(0);
  const directoryActive = useRef<AbortController | null>(null);
  const projectId = projects.some(p => p.id === selected) ? selected : '';
  const [tab, setTab] = useState<Tab>('observations');
  const [kind, setKind] = useState<ObservationKind>('production');
  const [catalog, setCatalog] = useState<CatalogKind>('software');
  const [draft, setDraft] = useState(defaultRange);
  const [applied, setApplied] = useState<TimeFilters & {device?: string}>(() => ({start: new Date(draft.start).toISOString(), end: new Date(draft.end).toISOString()}));
  const [parent, setParent] = useState<string>();
  const [before, setBefore] = useState<string>();
  const [cursor, setCursor] = useState<{id: string; offset: number; limit: number} | null>(null);
  const [retry, setRetry] = useState(0);
  const [status, setStatus] = useState<ProductionStatus | null>(null);
  const [page, setPage] = useState<ProductionPage | null>(null);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState('');
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const active = useRef<AbortController | null>(null);
  const startInput = useRef<HTMLInputElement>(null);
  const sourceKind: SourceKind = tab === 'catalog' ? catalog : tab === 'evidence' ? 'evidence' : tab === 'statistics' ? `${kind}_statistics` : kind;

  // Invalidate before the next render, including transports that ignore cancellation.
  function clear() { generation.current++; active.current?.abort(); setPage(null); setStatus(null); setError(''); setLoading(false); }
  function resetSource() { clear(); setCursor(null); setBefore(undefined); }
  useEffect(() => {
    const controller = new AbortController();
    directoryActive.current = controller;
    const current = ++directoryGeneration.current;
    const isCurrent = () => current === directoryGeneration.current && !controller.signal.aborted;
    setDirectoryLoading(true); setDirectoryError('');
    if (!directoryBefore) { setProjects([]); setSelected(''); resetSource(); setGlobalStatus(null); setDirectoryReady(false); setDirectoryNext(null); }
    async function loadDirectory() {
      try {
        const global = await api.productionStatus(undefined, controller.signal);
        if (!isCurrent()) return;
        setGlobalStatus(global);
        if (!global.configured) { setProjects([]); setSelected(''); resetSource(); setDirectoryReady(false); setDirectoryNext(null); return; }
        const result = await api.productionProjects({before_id: directoryBefore}, controller.signal);
        if (!isCurrent()) return;
        setProjects(old => directoryBefore ? [...old, ...result.items.filter(item => !old.some(p => p.id === item.id))] : result.items);
        setDirectoryReady(true);
        setDirectoryNext(result.has_more ? result.next_before_id : null);
      } catch (failure) {
        if (isCurrent()) {
          const forbidden = failure instanceof WorkflowError && (failure.status === 403 || failure.status === 401);
          setDirectoryError(forbidden ? '无权访问产测管理，请重新登录或联系管理员。' : '源项目目录暂不可用，请稍后重试。');
          if (forbidden) { setProjects([]); setSelected(''); resetSource(); }
        }
      } finally { if (isCurrent()) setDirectoryLoading(false); }
    }
    void loadDirectory();
    return () => { controller.abort(); };
  }, [api, directoryBefore, directoryRetry]);

  useEffect(() => {
    const controller = new AbortController();
    active.current = controller;
    const current = ++generation.current;
    setPage(null); setStatus(null); setError(''); setLoading(Boolean(projectId));
    const isCurrent = () => current === generation.current && !controller.signal.aborted;
    async function load() {
      if (!projectId) return;
      try {
        const capabilities = await api.productionStatus(projectId, controller.signal);
        if (!isCurrent()) return;
        setStatus(capabilities);
        if (!capabilities.configured || !capabilities.capabilities[sourceKind].available) return;
        let result: ProductionPage;
        if (cursor) result = await api.productionSnapshot(projectId, cursor.id, cursor.offset, cursor.limit, controller.signal);
        else switch (tab) {
          case 'observations': result = await api.productionObservations(projectId, {...applied, kind}, controller.signal); break;
          case 'catalog': result = await api.productionCatalog(projectId, catalog, {parent_id: parent, before_id: before}, controller.signal); break;
          case 'evidence': {
            const evidenceFilters = {...applied};
            delete evidenceFilters.device;
            result = await api.productionEvidence(projectId, {...evidenceFilters, before_id: before}, controller.signal); break;
          }
          case 'statistics': result = await api.productionStatistics(projectId, {...applied, kind}, controller.signal); break;
        }
        if (isCurrent()) setPage(result);
      } catch (failure) {
        if (isCurrent()) setError(failure instanceof WorkflowError && failure.status === 404 ? '源项目不存在或已移除，请刷新目录后重新选择。' : failure instanceof WorkflowError && (failure.status === 403 || failure.status === 401) ? '无权访问产测管理，请重新登录或联系管理员。' : failure instanceof WorkflowError && failure.status === 503 ? '数据源暂不可用，请稍后重试。' : failure instanceof WorkflowError && failure.status === 410 ? '观测快照已过期，请重新查询。' : '读取产测数据失败，请重试。');
      } finally { if (isCurrent()) setLoading(false); }
    }
    void load();
    return () => { controller.abort(); };
  }, [api, projectId, tab, kind, catalog, sourceKind, applied, parent, before, cursor, retry]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const start = new Date(draft.start), end = new Date(draft.end);
    if (tab !== 'catalog' && (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end <= start || end.getTime() - start.getTime() > 31 * 86400000)) { setValidation('请选择有效的开始和结束时间，范围须大于 0 且不超过 31 天。'); return; }
    const hasParent = catalog === 'software_versions' || catalog === 'config_versions';
    if (tab === 'catalog' && hasParent && draft.parent && !/^[1-9][0-9]{0,19}$/.test(draft.parent)) { setValidation('父记录 ID 必须是有效正整数。'); return; }
    resetSource(); setValidation('');
    if (tab === 'catalog') { setParent(hasParent && draft.parent ? draft.parent : undefined); setRetry(r => r + 1); }
    else setApplied({start: start.toISOString(), end: end.toISOString(), ...(draft.sn ? {sn: draft.sn} : {}), ...(tab !== 'evidence' && draft.device ? {device: draft.device} : {})});
  }
  function snapshot(offset: number) { if (!page) return; clear(); setCursor({id: page.snapshot_id, offset, limit: page.limit}); }
  const available = status?.capabilities[sourceKind].available;
  const columns = tab === 'evidence' ? ['id', 'csn', 'toolsname', 'devicename', 'state', 'createtime'] : tab === 'catalog' ? ['id', 'name', 'versions', 'softwareid', 'configid', 'state'] : ['timestamp', 'sn', 'devicename', 'status', 'errorcode'];

  return <section className="wf-production-tools" aria-label="产测管理工作区">
    <h2>产测管理</h2>
    <p>外部源只读观测；源记录与工具配置审核单不代表平台测试、标定或质量放行。</p>
    {directoryLoading && <p role="status">正在读取源项目目录…</p>}
    {globalStatus && !globalStatus.configured && <p>尚未配置产测数据源，请联系管理员。</p>}
    {directoryError && <p role="alert">{directoryError}</p>}
    {directoryReady && !directoryLoading && !directoryError && projects.length === 0 && <p>源项目目录暂无项目</p>}
    <div className="wf-production-directory">
      <button type="button" onClick={() => { directoryGeneration.current++; directoryActive.current?.abort(); resetSource(); setSelected(''); setProjects([]); setDirectoryBefore(undefined); setDirectoryRetry(r => r + 1); }}>刷新源项目目录</button>
      {directoryNext && <button type="button" disabled={directoryLoading} onClick={() => setDirectoryBefore(directoryNext)}>读取更多源项目</button>}
    </div>
    <form className="wf-production-filters" onSubmit={submit}>
      <label>源项目<select aria-label="源项目" value={projectId} onChange={e => { resetSource(); setSelected(e.target.value); setValidation(''); }}><option value="">请选择源项目</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      {tab !== 'catalog' && <>
        <label>开始时间<input ref={startInput} aria-label="开始时间" type="datetime-local" value={draft.start} onChange={e => setDraft(v => ({...v, start: e.target.value}))}/></label>
        <label>结束时间<input aria-label="结束时间" type="datetime-local" value={draft.end} onChange={e => setDraft(v => ({...v, end: e.target.value}))}/></label>
        <label>精确 SN<input aria-label="精确 SN" maxLength={200} value={draft.sn} onChange={e => setDraft(v => ({...v, sn: e.target.value}))}/></label>
        {tab !== 'evidence' && <label>精确设备<input aria-label="精确设备" maxLength={200} value={draft.device} onChange={e => setDraft(v => ({...v, device: e.target.value}))}/></label>}
      </>}
      {tab === 'catalog' ? <>
        <label>目录类型<select aria-label="目录类型" value={catalog} onChange={e => { resetSource(); setCatalog(e.target.value as CatalogKind); setParent(undefined); setDraft(v => ({...v, parent: ''})); }}>{catalogs.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        {(catalog === 'software_versions' || catalog === 'config_versions') && <label>父记录 ID<input aria-label="父记录 ID" inputMode="numeric" value={draft.parent} onChange={e => setDraft(v => ({...v, parent: e.target.value}))}/></label>}
      </> : tab !== 'evidence' && <label>观测类型<select aria-label="观测类型" value={kind} onChange={e => { resetSource(); setKind(e.target.value as ObservationKind); }}><option value="production">生产测试记录</option><option value="stopover">过站记录</option></select></label>}
      <button type="submit" disabled={!projectId}>查询产测数据</button>
    </form>
    <div className="wf-production-tabs" aria-label="产测数据分类">{tabs.map(([id, label]) => <button key={id} type="button" aria-pressed={tab === id} onClick={() => { if (id !== tab) { resetSource(); setTab(id); setValidation(''); } }}>{label}</button>)}</div>
    {!projectId && <p>请选择源项目</p>}
    {validation && <p role="alert">{validation}</p>}
    {loading && <p role="status">正在读取产测数据…</p>}
    {status && <p>已配置能力（不代表实时连通状态）：{status.configured ? Object.entries(status.capabilities).filter(([, value]) => value.available).map(([name]) => name).join('、') || '无可用能力' : '未配置'}</p>}
    {status && !status.configured && <p>尚未配置产测数据源</p>}
    {status?.configured && !available && <p role="alert">当前数据类型尚未配置可用能力，请联系管理员。</p>}
    {error && <p role="alert">{error}<button type="button" onClick={() => { clear(); setRetry(r => r + 1); }}>重试读取产测数据</button></p>}
    {page && projectId && <>
      <div className="wf-production-capture">
        <p>来源命名空间：{page.source_namespace} · 源项目 ID：{page.source_project_id} · 来源类型：{page.source_kind} · 采集时间：<time dateTime={page.captured_at}>{localTime(page.captured_at)}</time> · 捕获记录 {page.captured_count} · 本页 {page.items.length}</p>
        <p>应用范围：{page.filters.start ? `${localTime(page.filters.start)} 至 ${localTime(page.filters.end)}` : '目录元数据'}{page.filters.sn ? ` · 精确 SN：${text(page.filters.sn)}` : ''}{page.filters.device ? ` · 精确设备：${text(page.filters.device)}` : ''}{page.filters.parent_id ? ` · 父记录 ID：${text(page.filters.parent_id)}` : ''}</p>
        {!page.complete && <p role="status">仅显示部分记录，请缩小时间范围或指定 SN{page.truncation_reason ? `（${page.truncation_reason}）` : ''}</p>}
        {page.redacted_fields.length > 0 && <p>已隐藏字段：{page.redacted_fields.join('、')}</p>}
      </div>
      {tab === 'statistics' ? page.items.map((row, index) => <dl className="wf-production-statistics" key={index}>
        {statistics.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{text(row[key])}</dd></div>)}
        <div><dt>记录 PASS 比例</dt><dd>{row.record_pass_ratio === null ? '不适用' : typeof row.record_pass_ratio === 'number' ? `${(row.record_pass_ratio * 100).toFixed(2)}%` : '—'}</dd></div>
        <div><dt>统计一致性</dt><dd>{text(row.consistency)}</dd></div>
      </dl>) : page.items.length ? <div className="wf-production-table" role="region" aria-label="产测记录表" tabIndex={0}><table><thead><tr>{columns.map(name => <th key={name} scope="col">{name}</th>)}<th scope="col">记录详情</th>{tab === 'evidence' && <th scope="col">日志内容</th>}</tr></thead><tbody>{page.items.map((row, index) => <tr key={`${page.offset}-${index}`}>
        {columns.map(name => <td key={name}>{text(row[name])}</td>)}
        <td><details><summary>查看记录 {page.offset + index + 1}</summary><pre>{JSON.stringify(row, null, 2)}</pre></details></td>
        {tab === 'evidence' && <td>{status?.capabilities.evidence_content.available && evidenceId(row) ? <a href={api.productionEvidenceUrl(projectId, evidenceId(row)!)} download>下载日志证据</a> : '日志下载不可用'}</td>}
      </tr>)}</tbody></table></div> : <p>当前范围暂无记录</p>}
      {tab === 'statistics' && page.items.length === 0 && <p>当前范围暂无统计记录</p>}
      <div className="wf-production-paging" aria-label="观测快照分页">
        <button type="button" disabled={page.offset === 0} onClick={() => snapshot(Math.max(0, page.offset - page.limit))}>上一页快照</button>
        <span>第 {Math.floor(page.offset / page.limit) + 1} 页快照</span>
        <button type="button" disabled={!page.has_more} onClick={() => snapshot(page.offset + page.limit)}>下一页快照</button>
        {page.next_before_id !== null && (tab === 'catalog' || tab === 'evidence') && <button type="button" onClick={() => { const next = page.next_before_id!; clear(); setCursor(null); setBefore(next); }}>继续读取源记录</button>}
        {!page.complete && (tab === 'observations' || tab === 'statistics') && <button type="button" onClick={() => startInput.current?.focus()}>缩小范围重新查询</button>}
      </div>
    </>}
  </section>;
}
