import type {WorkflowApi} from '../api';
import type {IntentSummary} from './types';

// Recovery must finish reading durable metadata before permitting a new source
// intent. This never scans or mutates a source system.
export async function readIntentMetadata(api:WorkflowApi,projectId:string,signal?:AbortSignal):Promise<IntentSummary[]> {
 const records:IntentSummary[]=[];
 let offset=0,total=1;
 while(offset<total){
  if(signal?.aborted)throw new DOMException('Scope changed','AbortError');
  const page=await api.integrationIntents(projectId,50,offset,signal);
  records.push(...page.records);total=page.total;offset+=page.records.length;
  if(!page.records.length&&offset<total)throw new Error('原操作元数据尚未读取完整，请重试读取');
 }
 return records;
}
