import { expect, it } from 'vitest';
import { homeMetrics, priorityTasks, taskScope, deliveryQuantity } from './homePresentation';
import { project, order } from './testHelpers';
import type { ActorTaskPage, Dashboard } from './types';
const dashboard:Dashboard={project_ids:[project.id],project_count:1,counts:{work_order:17,unit:100},cards:[]};
const p={...project,quality_summary:{first_tested:0,first_passed:0,final_good:0,scrapped:0,open_nonconformances:3}};
const tasks:ActorTaskPage={items:[],total:80,offset:0,limit:50,truncated:true};
it('counts delivery projects using exact decimal positivity, and reads only defined counts',()=>{
 const tiny={...p,summary:{...p.summary,current_order_quantity:'0.0000000000000000000000001',remaining_to_ship:'0.0000000000000000000000001'}};
 expect(homeMetrics(dashboard,[tiny],true,tasks)).toEqual({delivery:1,quality:3,workOrders:17,tasks:80,scopeReady:true});
 expect(homeMetrics(dashboard,[{...p,summary:{...p.summary,current_order_quantity:'0'}}],true,tasks).delivery).toBe(0);
 expect(homeMetrics({...dashboard,counts:{}},[p],true,tasks).workOrders).toBeNull();
});
it('requires complete exact scope and valid fields, never turns absent data into zero',()=>{
 for(const ps of [[],[{...p,id:'other'}],[p,p]])expect(homeMetrics(dashboard,ps,true,null).delivery).toBeNull();
 expect(homeMetrics(dashboard,[p],false,null).quality).toBeNull();
 expect(homeMetrics({...dashboard,project_count:2},[p],true,null).delivery).toBeNull();
 expect(homeMetrics(null,[p],true,null).delivery).toBeNull();
 expect(homeMetrics(dashboard,[project],true,null).quality).toBeNull();
 for(const n of ['bad','-1','Infinity','1e2'])expect(homeMetrics(dashboard,[{...p,summary:{...p.summary,remaining_to_ship:n}}],true,null).delivery).toBeNull();
 expect(homeMetrics(dashboard,[{...p,quality_summary:{...p.quality_summary,open_nonconformances:-1}}],true,null).quality).toBeNull();
 expect(homeMetrics({...dashboard,project_ids:[],project_count:0},[],true,null).quality).toBe(0);
});
it('preserves mixed-unit delivery strings without aggregating quantities',()=>{
 const other={...p,id:'other',unit:{code:'kg',scale:2},summary:{...p.summary,remaining_to_ship:'2.50'}};
 expect(homeMetrics({...dashboard,project_ids:[p.id,other.id],project_count:2},[p,other],true,tasks).delivery).toBe(2);
 expect(deliveryQuantity(other,'remaining_to_ship')).toBe('2.50 kg');
 expect(deliveryQuantity({...other,summary:{...other.summary,remaining_to_ship:'bad'}},'remaining_to_ship')).toBe('—');
});
it('orders only loaded task page by evidence, stably, and discloses bounds',()=>{
 const item=(id:string,state:string,kind=order.kind)=>({category:'business' as const,title:'blocked danger title is not evidence',target:{...order,id,state,kind,blocking_reasons:[]},owner_id:null,owner_name:''});
 const loaded=[item('ordinary','open'),item('fail','fail','test'),item('open-ncr','open','nonconformance'),item('ordinary2','open')];
 expect(priorityTasks(loaded,3).map(t=>t.target.id)).toEqual(['fail','open-ncr','ordinary']);
 expect(taskScope({...tasks,items:loaded},3)).toContain('下界');
 expect(taskScope({...tasks,items:loaded},3)).toContain('本次读取 4 条');
 expect(taskScope({...tasks,items:loaded},3)).toContain('展示 3 条');
});
