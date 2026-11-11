import {useEffect,useState} from 'react';
import type {OEMWorkspaceProps} from '../OEMWorkspace';
import type {ObjectPage} from '../types';
export function MaterialTaskList({p}:{p:OEMWorkspaceProps}) {
 const [page,setPage]=useState<ObjectPage|null>(null),[offset,setOffset]=useState(0),[error,setError]=useState('');
 useEffect(()=>{if(!p.api.materialTasks)return;let active=true;const c=new AbortController();setPage(null);setError('');p.api.materialTasks(p.project.id,50,offset,c.signal).then(v=>{if(active)setPage(v);}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;c.abort();};},[p.api,p.project.id,p.project.version,offset]);
 return <section aria-label="项目物料任务"><h4>物料任务</h4>{error?<p role="alert">任务读取失败：{error}</p>:!page?<p role="status">正在读取任务…</p>:!page.items.length?<p>暂无物料任务</p>:<><ul>{page.items.map(t=><li key={t.id}><button className="wf-text-link" onClick={()=>p.requestLeave(()=>p.onOpen({projectId:p.project.id,kind:'material_task',id:t.id}))}>{t.title}</button> · {({pending:'待接单',processing:'处理中',verification:'待完成',closed:'已完成',cancelled:'已取消'} as Record<string,string>)[t.state]||t.state}</li>)}</ul>{offset>0&&<button onClick={()=>p.requestLeave(()=>setOffset(Math.max(0,offset-50)))}>上一页任务</button>}{offset+page.items.length<page.total&&<button onClick={()=>p.requestLeave(()=>setOffset(offset+50))}>下一页任务</button>}</>}</section>;
}
