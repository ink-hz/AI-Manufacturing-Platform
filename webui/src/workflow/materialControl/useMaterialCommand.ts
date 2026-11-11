import {useEffect,useRef} from 'react';
import type {WorkflowApi} from '../api';
import type {CommandFields,WorkflowCommand} from '../types';
export function useMaterialCommand(api:WorkflowApi,projectId:string){
 const pending=useRef<{key:string;command:WorkflowCommand}|null>(null),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[api,projectId]);
 async function execute(fields:CommandFields,version:number){
  const key=JSON.stringify([fields,version]);
  if(!pending.current||pending.current.key!==key)pending.current={key,command:{...fields,expected_version:version,operation_id:crypto.randomUUID()}};
  const result=await api.command(projectId,pending.current.command);
  if(!alive.current)return null;
  pending.current=null;return result;
 }
 return {execute,clear:()=>{pending.current=null;},isCurrent:()=>alive.current};
}
