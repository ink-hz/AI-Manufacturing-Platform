import { useEffect, useState } from 'react';
import type { WorkflowApi } from './api';
import type { ActorTaskPage, ProjectDetail, WorkflowTarget } from './types';
import type { TaskContext } from './navigationContext';
import { PageControls, ProjectScope } from './GlobalLedger';
import { label } from './labels';

export function GlobalTasks({api,context,onContext,projects,refresh,onRefresh,onOpen}: {
  api:WorkflowApi;context:TaskContext;onContext(value:TaskContext):void;projects:ProjectDetail[];
  refresh:number;onRefresh():void;onOpen(target:WorkflowTarget):void;
}) {
  const [page,setPage]=useState<ActorTaskPage|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    let active=true;setPage(null);setError('');
    api.tasks(50,context.offset,context.projectId||undefined).then(value=>{if(active)setPage(value);}).catch(e=>{if(active)setError(String(e));});
    return ()=>{active=false;};
  },[api,context.projectId,context.offset,refresh]);
  return <section aria-label="我的待处理事项"><h2>我的待处理事项</h2>
    <div className="mf-actions"><ProjectScope projects={projects} value={context.projectId} onChange={projectId=>onContext({projectId,offset:0})}/><button onClick={onRefresh}>刷新事项</button></div>
    <p>按当前职责与实际责任人列出的待办，点击查看原始对象。</p>
    {error?<p role="alert">{error}<button onClick={onRefresh}>重试读取事项</button></p>:!page?<p role="status">正在读取当前责任事项…</p>:<>
      <p role="status">{page.truncated?'可用事项':'事项合计'} {page.total} 条</p>
      {page.truncated&&<p>每项目事项查询有界，当前可用事项并非全部待办；请进入相应业务台账继续查看。</p>}
      {!page.items.length?<p>{page.total ? "当前页暂无事项，请返回上一页。" : "当前读取范围内没有分配给你的待处理事项。"}</p>:<div className="wf-table-scroll"><table><thead><tr><th>业务对象</th><th>所属项目</th><th>责任</th><th>待办</th><th>状态</th><th>阻断</th></tr></thead>
        <tbody>{page.items.map((task,i)=><tr key={task.target.project_id+task.target.id+i}>
          <td><button onClick={()=>onOpen({projectId:task.target.project_id,kind:task.target.kind,id:task.target.id})}>{task.target.title}</button></td>
          <td>{projects.find(p=>p.id===task.target.project_id)?.name||task.target.project_id}</td><td>{task.owner_id?'责任人 '+task.owner_name:'当前职责可处理'}</td><td>{task.title}</td>
          <td>{label(task.target.state)}</td><td>{task.target.blocking_reasons.join('；')||'无'}</td>
        </tr>)}</tbody></table></div>}
      <PageControls page={page} onPage={offset=>onContext({...context,offset})}/>
    </>}
  </section>;
}
