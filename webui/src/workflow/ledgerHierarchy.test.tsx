import { expect, it } from 'vitest';
import { workflowView, order, project } from './testHelpers';
it('separates ledger total from current-page attention and badges real object state',async()=>{
 const rows=[{...order,blocking_reasons:[]},{...order,id:'failed',kind:'test' as const,state:'fail',blocking_reasons:[]}];
 const v=await workflowView({readLedger:async(_kind,limit,offset)=>({items:rows,total:151,limit,offset})});
 try{await v.click('质量与追溯');expect(v.host.textContent).toContain('检验测试合计 151 条');expect(v.host.textContent).toContain('本页需关注 1 条');expect(v.host.querySelectorAll('table .wf-status')).toHaveLength(2);await v.click('ORDER-001');expect(v.host.querySelector('.wf-detail .wf-status')).not.toBeNull();}finally{await v.dispose();}
});
it('applies shared status semantics and page-scoped attention to tasks and project tables',async()=>{
 const v=await workflowView({readTasks:async(limit,offset)=>({items:[{category:'business',title:'处理',target:order,owner_id:null,owner_name:''}],total:51,limit,offset,truncated:false})});
 try{await v.click('事项');expect(v.host.textContent).toContain('本页需关注 1 条');expect(v.host.querySelector('table .wf-status')?.textContent).toContain('open');await v.click('制造项目');await v.click(project.name);expect(v.host.querySelector('table .wf-status')).not.toBeNull();}finally{await v.dispose();}
});
