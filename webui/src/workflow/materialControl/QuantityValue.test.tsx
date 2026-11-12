// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { QuantityValue } from './QuantityValue';

it('preserves mock and unknown identities and lazily reveals exact inputs', async () => {
 const host = document.createElement('div'); const root = createRoot(host);
 const source = {reference:'ref-1',project_id:'p1',object_kind:'receipt',object_id:'r1',system:'MES',source_type:'receipt',external_id:'ext',version:2,namespace:'site',origin:'mock',environment:'test',occurred_at:'2026-01-01T00:00:00Z',collected_at:'2026-01-02T00:00:00Z',coverage:'complete',value:'1.25',unit:'EA',meaning:'input'} as const;
 const quantity = {value:'1.25',unit:'EA',meaning:'result',origins:['mock','manual','native','unknown'],environments:['test','unknown'],fact_role:'confirmed',observed_at:null,collected_at:null,coverage:'partial',source_refs:[source],input_refs:['ref-1']} as const;
 await act(async()=>root.render(<QuantityValue quantity={quantity as any} value="99" unit="EA" title="需求"/>));
 expect(host.textContent).toContain('1.25 EA'); expect(host.textContent).toContain('模拟'); expect(host.textContent).toContain('手工'); expect(host.textContent).toContain('原生'); expect(host.textContent).toContain('来源待核对'); expect(host.textContent).toContain('时间待核对'); expect(host.textContent).not.toContain('ref-1');
 await act(async()=>{const details = host.querySelector('details')!; details.open = true; details.dispatchEvent(new Event('toggle')); });
 expect(host.textContent).toContain('ref-1'); expect(host.textContent).toContain('r1'); expect(host.textContent).toContain('2026-01-01'); expect(host.textContent).toContain('2026-01-02');
 await act(async()=>root.unmount());
});
it('does not replace a present null projection with an old scalar; old responses are unverified', async()=>{
 const host=document.createElement('div'); const root=createRoot(host);
 const q={value:null,unit:'EA',meaning:'result',origins:['unknown'],environments:['unknown'],fact_role:'unknown',observed_at:null,collected_at:null,coverage:'unknown',source_refs:[],input_refs:[]} as const;
 await act(async()=>root.render(<QuantityValue quantity={q as any} value="99" unit="EA" title="需求"/>));
 expect(host.textContent).toContain('未提供'); expect(host.textContent).not.toContain('99');
 await act(async()=>root.render(<QuantityValue value="99" unit="EA" title="需求"/>));
 expect(host.textContent).toContain('99 EA'); expect(host.textContent).toContain('来源待核对');
 await act(async()=>root.unmount());
});
