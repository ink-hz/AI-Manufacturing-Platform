import {SystemStepPanel} from './integrations/SystemStepPanel';
import { useEffect, useState } from 'react';
import type { WorkflowApi } from './api';
import type { ActorTaskPage, Dashboard, ObjectKind, ProjectDetail, WorkflowTarget } from './types';
import type { BusinessModule } from './navigationContext';
import { homeMetrics, deliveryQuantity, priorityTasks, taskScope } from './homePresentation';
import { StatusBadge } from './StatusBadge';
import { objectTitle, label } from './labels';
export type HomeDestination = BusinessModule | 'tasks' | 'projects';
export function WorkflowHome({data, projects, projectsReady, dashboardError, projectsError, api, refresh, active, onRefresh, onOpen, onNavigate, onDirty=()=>{}, requestLeave=f=>f(), readOnly=false}: {
  data: Dashboard | null; projects: ProjectDetail[]; projectsReady: boolean;
  dashboardError: string; projectsError: string; api: WorkflowApi; refresh: number; active: boolean;
  onRefresh(): void; onOpen(target: WorkflowTarget): void;
  readOnly?:boolean; onDirty?(key:string,dirty:boolean):void; requestLeave?(action:()=>void):void;
  onNavigate(module: HomeDestination, kind?: ObjectKind, projectId?: string): void;
}) {
  const [biProjectId,setBiProjectId]=useState('');
  const biProject=projects.find(p=>p.id===biProjectId);
  const [tasks, setTasks] = useState<ActorTaskPage | null>(null), [taskError, setTaskError] = useState(''), [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController(); let current = true;
    setTasks(null); setTaskError('');
    api.tasks(50, 0, undefined, controller.signal).then(value => { if (current) setTasks(value); }).catch(error => { if (current) setTaskError(String(error)); });
    return () => { current = false; controller.abort(); };
  }, [api, refresh, retry, active]);
  const metrics = homeMetrics(data, projects, projectsReady, tasks);
  const queue = priorityTasks(tasks?.items || []);
  const projectState = projectsError ? `项目资料读取失败：${projectsError}` : !projectsReady ? '正在读取项目资料…' : !data ? '等待业务概览范围' : !metrics.scopeReady ? '项目资料与概览范围不一致，暂不可汇总' : '';
  const cards = [
    {title: '待交付项目', value: metrics.delivery, note: '当前订单与待发数量均大于 0 的项目', module: 'orders' as const, kind: 'order_line' as const},
    {title: '当前可处理事项', value: metrics.tasks, note: tasks?.truncated ? '至少此数量 · 每项目查询有界' : '按当前职责与实际责任人', module: 'tasks' as const},
    {title: '未闭环不合格', value: metrics.quality, note: '授权范围项目的未闭环 NCR', module: 'quality' as const, kind: 'nonconformance' as const},
    {title: '制造工单', value: metrics.workOrders, note: '授权范围内全部工单记录', module: 'execution' as const, kind: 'work_order' as const},
  ];
  return <section className="wf-home" aria-label="授权项目业务概览">
    <div className="wf-section-heading"><p className="mf-meta">先处理责任事项，再核对订单交付与质量处置。</p><button onClick={onRefresh}>刷新工作台</button></div>
    {dashboardError ? <p role="alert">概览读取失败：{dashboardError} <button onClick={onRefresh}>重试读取概览</button></p> : !data && <p role="status">正在读取业务概览…</p>}
    <div className="wf-home-metrics">{cards.map(card => <article className="wf-home-metric" key={card.title}>
      <button className="wf-text-link" onClick={() => onNavigate(card.module, card.kind)}>{card.title}</button>
      <strong className="wf-metric-value">{card.value === null ? '—' : `${card.title === '当前可处理事项' && tasks?.truncated ? '≥ ' : ''}${card.value}`}</strong>
      <p>{card.note}</p>
      {card.value === null && <small>{card.title === '当前可处理事项' ? taskError ? '读取失败，可重试' : '正在读取事项…' : card.title === '制造工单' ? data ? '工单统计未提供' : '等待概览' : projectState || '所需汇总资料未提供或无效'}</small>}
    </article>)}</div>
    <div className="mf-actions" aria-label="工程与实验室入口"><button onClick={()=>onNavigate("introduction","npi")}>工程导入与资产</button><button onClick={()=>onNavigate("laboratory","test_run")}>测试运行与标定</button></div>
    <details><summary>项目 BI 截止快照</summary><label>BI 项目<select aria-label="BI 项目" value={biProjectId} onChange={e=>{const id=e.target.value;requestLeave(()=>setBiProjectId(id));}}><option value="">选择授权项目</option>{projects.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label>{biProject&&<SystemStepPanel api={api} project={biProject} context="home" selected={null} onChanged={()=>onRefresh()} onOpen={onOpen} onDirty={onDirty} requestLeave={requestLeave} readOnly={readOnly}/>}</details>
    <div className="wf-home-columns">
      <section className="wf-panel wf-priority" aria-label="优先事项">
        <div className="wf-section-heading"><h2>优先事项</h2><button className="wf-text-link" onClick={() => onNavigate('tasks')}>查看全部事项</button></div>
        {taskError ? <p role="alert">事项读取失败：{taskError} <button onClick={() => setRetry(n => n + 1)}>重试读取事项</button></p> : !tasks ? <p role="status">正在读取当前责任事项…</p> : <>
          <p className="mf-meta">{taskScope(tasks, queue.length)}</p>
          {!queue.length ? <p className="wf-empty">当前读取范围内没有分配给你的待处理事项。</p> : <ol className="wf-task-list">{queue.map((task, index) => <li key={`${task.target.project_id}-${task.target.kind}-${task.target.id}-${index}`}>
            <div className="wf-section-heading"><button className="wf-text-link" onClick={() => onOpen({projectId: task.target.project_id, kind: task.target.kind, id: task.target.id})}>{objectTitle(task.target)}</button><StatusBadge state={task.target.state} kind={task.target.kind} blocking={task.target.blocking_reasons}/></div>
            <p>{task.title}</p><p className="mf-meta">{projects.find(p => p.id === task.target.project_id)?.name || task.target.project_id} · {label(task.target.kind)} · {task.owner_id ? `责任人 ${task.owner_name}` : '当前职责可处理'}</p>
            {!!task.target.blocking_reasons.length && <p className="wf-attention-text">阻断：{task.target.blocking_reasons.map(label).join('；')}</p>}
          </li>)}</ol>}
        </>}
      </section>
      <section className="wf-panel" aria-label="交付概况">
        <div className="wf-section-heading"><h2>交付概况</h2><button className="wf-text-link" onClick={() => onNavigate('orders', 'order_line')}>订单台账</button></div>
        <p className="mf-meta">按项目保留原数量与单位；待发与待验收分别核对，不代表质量或成本关账。</p>
        {projectState ? <p role={projectsError ? 'alert' : 'status'}>{projectState}{(projectsError || (projectsReady && data)) && <button onClick={onRefresh}>重试读取项目资料</button>}</p> : !projects.length ? <p className="wf-empty">当前授权范围暂无项目。</p> : <>
          <p className="mf-meta">展示 {Math.min(projects.length, 6)} / {projects.length} 个授权项目；按项目资料顺序。</p>
          <ul className="wf-delivery-list">{projects.slice(0, 6).map(p => <li key={p.id}>
            <div className="wf-section-heading"><strong>{p.name}</strong><button className="wf-text-link" aria-label={`查看${p.name}订单`} onClick={() => onNavigate('orders', 'order_line', p.id)}>查看订单</button></div>
            <p className="mf-meta">{p.customer_id} · {p.product}</p>
            <dl><div><dt>待发</dt><dd>{deliveryQuantity(p, 'remaining_to_ship')}</dd></div><div><dt>待验收</dt><dd>{deliveryQuantity(p, 'remaining_to_accept')}</dd></div></dl>
          </li>)}</ul>
          {projects.length > 6 && <button className="wf-text-link" onClick={() => onNavigate('projects')}>查看全部制造项目</button>}
        </>}
      </section>
    </div>
    <nav className="wf-home-shortcuts" aria-label="业务快捷入口">{([
      ['orders', '订单与交付', '核对订单与发货'], ['supply', '计划与物料', '核对物料准备'], ['execution', '工单与执行', '跟进固定版本工单'], ['quality', '质量与追溯', '检验与质量处置'],
    ] as const).map(([module, title, description]) => <button key={module} aria-label={`进入${title}`} onClick={() => onNavigate(module)}><strong>{title}</strong><span>{description}</span></button>)}</nav>
    {!!data?.cards?.length && <section className="wf-record-entries" aria-label="业务记录入口"><h2>业务记录入口</h2><p className="mf-meta">概览已读取范围中的 {Math.min(data.cards.length, 6)} 条记录；完整记录请进入业务台账。</p><div className="mf-actions">{data.cards.slice(0, 6).map(row => <span key={row.project_id + row.kind + row.id}><button className="wf-text-link" onClick={() => onOpen({projectId: row.project_id, kind: row.kind, id: row.id})}>{objectTitle(row)}</button><small>{projects.find(p => p.id === row.project_id)?.name || row.project_id} · {label(row.kind)}</small></span>)}</div></section>}
  </section>;
}
