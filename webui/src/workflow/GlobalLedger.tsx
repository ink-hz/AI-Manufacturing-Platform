import { useEffect, useState } from 'react';
import type { WorkflowApi } from './api';
import type { ObjectPage, ProjectDetail, WorkflowTarget } from './types';
import { businessModules, type BusinessModule, type LedgerContext } from './navigationContext';
import { label } from './labels';
import { StatusBadge, needsAttention } from './StatusBadge';
import { compactSource } from './sourcePresentation';

export function ProjectScope({projects, value, onChange}: {projects:ProjectDetail[];value:string;onChange(value:string):void}) {
  return <label>所属项目筛选 <select aria-label="所属项目筛选" value={value} onChange={e=>onChange(e.target.value)}>
    <option value="">全部授权项目</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name} · {p.customer_id} · {p.product}</option>)}
  </select></label>;
}
export function PageControls({page, onPage}: {page:{total:number;limit:number;offset:number};onPage(offset:number):void}) {
  return <div className="mf-actions wf-pagination" aria-label="台账分页">
    <button disabled={!page.offset} onClick={()=>onPage(Math.max(0,page.offset-page.limit))}>上一页</button>
    <span>第 {Math.floor(page.offset/page.limit)+1} 页 · 每页 {page.limit} 条</span>
    <button disabled={page.offset+page.limit>=page.total} onClick={()=>onPage(page.offset+page.limit)}>下一页</button>
  </div>;
}
export function GlobalLedger({api,module,context,onContext,projects,refresh,onRefresh,onOpen,onProject}: {
  api:WorkflowApi;module:BusinessModule;context:LedgerContext;onContext(value:LedgerContext):void;
  projects:ProjectDetail[];refresh:number;onRefresh():void;onOpen(target:WorkflowTarget):void;
  onProject(project:ProjectDetail, trace?:boolean):void;
}) {
  const [page,setPage]=useState<ObjectPage|null>(null),[error,setError]=useState('');
  const config=businessModules[module], tab=config.tabs.find(t=>t.kind===context.kind)!;
  const selected=projects.find(p=>p.id===context.projectId);
  useEffect(()=>{
    const controller=new AbortController();let active=true;setPage(null);setError('');
    api.ledger(context.kind,50,context.offset,context.projectId||undefined,controller.signal)
      .then(value=>{if(active)setPage(value);}).catch(e=>{if(active)setError(String(e));});
    return ()=>{active=false;controller.abort();};
  },[api,module,context.kind,context.offset,context.projectId,refresh]);
  return <section className="wf-global-ledger wf-panel" aria-label={config.title}>
    <h2>{config.title}</h2>
    <p className="mf-meta">{({introduction:"跟进导入证据、当前批量资格与资产验证",laboratory:"核对实际测试运行、标定读回和单台履历",orders:"核对订单承诺、发货与验收",supply:"核对计划依据、到货与物料准备",execution:"跟进固定版本工单与执行中断",quality:"处置不合格、核对独立放行与追溯",collaboration:"核对权威回执与来源差异"})[module]}</p>
    <div className="mf-tabs" aria-label="业务类型">{config.tabs.map(t=><button key={t.kind} aria-pressed={context.kind===t.kind} onClick={()=>onContext({...context,kind:t.kind,offset:0})}>{t.title}</button>)}</div>
    <div className="mf-actions wf-ledger-toolbar">
      <ProjectScope projects={projects} value={context.projectId} onChange={projectId=>onContext({...context,projectId,offset:0})}/>
      <button onClick={onRefresh}>刷新台账</button>
      <button disabled={!selected} onClick={()=>selected&&onProject(selected)}>进入项目办理</button>
      {module==='quality'&&<button disabled={!selected} onClick={()=>selected&&onProject(selected,true)}>追溯查询</button>}
    </div>
    <p className="mf-meta">查看全部授权项目的业务记录；办理或追溯前请选择所属项目。</p>
    {error?<p role="alert">{error}<button onClick={onRefresh}>重试读取台账</button></p>:!page?<p role="status">正在读取{tab.title}…</p>:<>
      <div className="wf-ledger-summary" role="status"><strong>{tab.title}合计 {page.total} 条</strong><span>本页 {page.items.length} 条 · 本页需关注 {page.items.filter(needsAttention).length} 条</span></div>
      {!page.items.length?<p>{page.total ? "当前页" : "当前范围"}暂无{tab.title}记录。{page.total > 0 && "请返回上一页。"}</p>:<div className="wf-table-scroll"><table><thead><tr>
        <th>{tab.column}</th><th>客户</th><th>产品</th><th>所属项目</th><th>数量</th><th>状态</th><th>来源</th><th>阻断</th>
      </tr></thead><tbody>{page.items.map(row=>{const p=projects.find(p=>p.id===row.project_id);return <tr key={row.project_id+row.kind+row.id} className={needsAttention(row)?"wf-attention-row":undefined}>
        <td><button className="wf-text-link" onClick={()=>onOpen({projectId:row.project_id,kind:row.kind,id:row.id})}>{row.title}</button></td>
        <td>{p?.customer_id||'—'}</td><td>{p?.product||'—'}</td><td>{p?.name||row.project_id}</td>
        <td className="wf-quantity">{row.quantity??'—'} {row.unit}</td><td><StatusBadge state={row.state} kind={row.kind} blocking={row.blocking_reasons}/></td>
        <td className="wf-source">{row.source?compactSource(row.source):'无外部来源'}</td>
        <td>{row.blocking_reasons.map(label).join('；')||'无'}</td>
      </tr>;})}</tbody></table></div>}
      <PageControls page={page} onPage={offset=>onContext({...context,offset})}/>
    </>}
  </section>;
}
