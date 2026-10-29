import { expect, it } from 'vitest';
import { workflowView, bootstrap } from './workflow/testHelpers';
it.each([undefined, {...bootstrap,workflow_available:false,legacy_access:true}])('requires available workflow bootstrap without opening the retired product',async(value)=>{
 const v=await workflowView({options:{bootstrap:value}});
 try{expect(v.host.querySelector('[role="alert"]')?.textContent).toContain('不可用');expect(v.requests).toHaveLength(0);expect(v.host.textContent).not.toContain('旧项目');}finally{await v.dispose();}
});
