import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {DeliveryForms} from './forms/DeliveryForms';
import {DeliveryWorkspace} from './DeliveryWorkspace';
import {WorkflowError} from './api';
import type {ProjectDetail} from './types';
const id='00000000-0000-4000-8000-000000000001';
const project={id,version:7,unit:{code:'piece',scale:0},customer_id:'Customer',allowed_actions:['shipment.request','delivery.sign','delivery.accept','closure.record'],contract:{acceptance_required:true}} as ProjectDetail;
const item=(kind:string)=>({id,project_id:id,kind,title:kind==='unit'?'SN-001':'Order 100',state:'open',version:1,blocking_reasons:[],next_actions:[]});
const api={objects:vi.fn(async(_p:string,k:string)=>({items:['unit','order_line'].includes(k)?[item(k)]:[],total:1,limit:50,offset:0})),members:vi.fn(async()=>({items:[{user_id:id,display_name:'Quality Engineer',active:true,roles:['quality']}]})),object:vi.fn(async(_p:string,k:string)=>({value:{kind:k,id,remaining_to_ship:'40',remaining_to_accept:'40',signed:'60',accepted:'60',current_quantity:'100',unit:'piece'}})),command:vi.fn()} as any;
let host:HTMLDivElement,root:Root;
beforeEach(()=>{host=document.createElement('div');document.body.append(host);root=createRoot(host);api.command.mockReset();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
const props=()=>({api,project,onChanged:vi.fn(),onOpen:vi.fn(),onDirty:vi.fn(),readOnly:false,requestLeave:(f:()=>void)=>f()});
async function click(text:string){const b=[...host.querySelectorAll('button')].find(x=>x.textContent===text);expect(b,text).toBeTruthy();await act(async()=>b!.click());}
it('preserves serial and box selections after an oversized request fails',async()=>{
 api.command.mockRejectedValue(new WorkflowError(409,'PRECONDITION_FAILED',['Remaining 40']));
 const units=Array.from({length:41},(_,index)=>({...item('unit'),id:`unit-${index}`,title:`SN-${index}`}));
 await act(async()=>root.render(<DeliveryForms {...props()} action="shipment.request" units={units as any} orders={[item('order_line')] as any} shipments={[]} members={[]} lots={[]} ecos={[]} reservations={[]}/>));
 for(const checkbox of [...host.querySelectorAll('input[type="checkbox"]')] as HTMLInputElement[])await act(async()=>checkbox.click());
 await click('添加包装箱');
 const name=host.querySelector('[aria-label="箱号 1"]') as HTMLInputElement;
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(name,'BOX-A');name.dispatchEvent(new Event('input',{bubbles:true}));});
 for(const checkbox of ([...host.querySelectorAll('input[type="checkbox"]')] as HTMLInputElement[]).slice(41))await act(async()=>checkbox.click());
 await click('提交发货申请');
 expect(api.command.mock.calls[0][1]).toMatchObject({action:'shipment.request',unit_ids:units.map(u=>u.id),quantity:'41',boxes:[{box_id:'BOX-A',unit_ids:units.map(u=>u.id)}]});
 expect(([...host.querySelectorAll('input[type="checkbox"]')] as HTMLInputElement[]).every(box=>box.checked)).toBe(true);
 expect((host.querySelector('[aria-label="箱号 1"]') as HTMLInputElement).value).toBe('BOX-A');
 expect(host.textContent).toContain('Remaining 40');
});
it('shows independent closure cards and bounded named members without directory API',async()=>{
 await act(async()=>root.render(<DeliveryWorkspace {...props()}/>));
 await act(async()=>{await new Promise(r=>setTimeout(r,0));});
 for(const text of ['履约关闭','质量关闭','成本关闭'])expect(host.textContent).toContain(text);
 expect(api.members).toHaveBeenCalledWith(id,50,0);
 expect(api.objects).toHaveBeenCalledWith(id,'unit',50,0);
});
