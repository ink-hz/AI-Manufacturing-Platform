import type {MaterialOverview,MaterialProject,MesOrderMaterialsData,MaterialFilters,TaskReferencePage} from './types';
import type {ObjectPage} from '../types';
type Request = <T>(path:string, method?:string, body?:unknown, signal?:AbortSignal)=>Promise<T>;
export function materialControlApi(request:Request) {
 const project=(id:string)=>'/projects/'+encodeURIComponent(id);
 return {
  mesOrderMaterials:(id:string,workOrderId:string,signal?:AbortSignal)=>request<MesOrderMaterialsData>(project(id)+`/work-orders/${encodeURIComponent(workOrderId)}/mes-materials`,'GET',undefined,signal),
  materialOverview:(limit=50,offset=0,signal?:AbortSignal)=>request<MaterialOverview>(`/material-control/overview?limit=${limit}&offset=${offset}`,'GET',undefined,signal),
  materialProject:(id:string,limit=50,offset=0,signal?:AbortSignal,filters?:MaterialFilters)=>{const query=new URLSearchParams({limit:String(limit),offset:String(offset)}); if(filters?.search) query.set('search',filters.search); if(filters?.problem) query.set('problem',filters.problem); if(filters?.work_order_id) query.set('work_order_id',filters.work_order_id); return request<MaterialProject>(project(id)+`/material-control?${query}`,'GET',undefined,signal);},
  materialRequirement:(id:string,requirementId:string,signal?:AbortSignal)=>request<MaterialProject>(project(id)+`/material-control?limit=50&offset=0&requirement_id=${encodeURIComponent(requirementId)}`,'GET',undefined,signal),
  materialTasks:(id:string,limit=50,offset=0,signal?:AbortSignal)=>request<ObjectPage>(project(id)+`/material-tasks?limit=${limit}&offset=${offset}`,'GET',undefined,signal),
  materialReferences: (id: string, taskKind: 'verify' | 'iqc', search: string, limit: number,
    offset: number, signal?: AbortSignal, requirementId?: string, options?: { receipt_id?: string }) => {
    const query = new URLSearchParams({ task_kind: taskKind, search, limit: String(limit), offset: String(offset) });
    if (requirementId) query.set('requirement_id', requirementId);
    if (options?.receipt_id) query.set('receipt_id', options.receipt_id);
    return request<TaskReferencePage>(project(id) + `/material-task-references?${query}`, 'GET', undefined, signal);
  },
  materialAssignees:(id:string,kind:'iqc'|'trace'|'verify',signal?:AbortSignal)=>request<{items:{id:string;display_name:string}[];total:number}>(project(id)+`/material-control/assignees?task_kind=${kind}`,'GET',undefined,signal),
 };
}

export function validateReferencePage(page: TaskReferencePage, projectId: string, taskKind: 'verify' | 'iqc'): TaskReferencePage {
  if (page.project_id !== projectId || page.task_kind !== taskKind ||
      !Number.isInteger(page.project_version) || page.project_version < 1)
    throw new Error('引用页面身份或版本不匹配');
  return page;
}
