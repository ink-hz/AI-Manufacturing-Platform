import {describe,it,expect} from 'vitest';
import {BUSINESS_STEPS} from './businessSteps';
describe('business steps in consuming workspaces',()=>{
 it('covers each business context with real responsibility, inputs, outputs and a next action',()=>{
   for(const context of ['orders','engineering','introduction','supply','handoff','execution','quality','laboratory','delivery','trace','home']){
     const steps=BUSINESS_STEPS.filter(s=>s.context===context);
     expect(steps.length,context).toBeGreaterThan(0);
     for(const step of steps){expect(step.responsibleSystem).toBeTruthy();expect(step.inputTypes.length).toBeGreaterThan(0);expect(step.outputTypes.length).toBeGreaterThan(0);expect(step.receiptType).toBeTruthy();expect(step.title).toBeTruthy();}
   }
 });
 it('keeps separate sign, acceptance, physical delivery, posting and manual handoff',()=>{
   const op=(id:string)=>BUSINESS_STEPS.find(s=>s.id===id)?.operationKind;
   expect(op('delivery.customer-receipt')).toBe('customer.receive_shipment');
   expect(op('delivery.customer-acceptance')).toBe('customer.confirm_delivery');
   expect(op('handoff.manual-receipt')).toBeNull();
   expect(op('delivery.wms-shipment')).toBe('wms.ship');
   expect(op('home.bi-snapshot')).toBe('bi.refresh');
 });
});
