// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { QuantityValue } from './QuantityValue';

it('preserves mock and unknown identities and lazily reveals exact inputs', async () => {
 const host = document.createElement('div'); const root = createRoot(host);
 const source = {reference:'ref-1',project_id:'p1',object_kind:'receipt',object_id:'r1',system:'MES',source_type:'receipt',external_id:'ext',version:2,namespace:'site',origin:'mock',environment:'mock',occurred_at:'2026-01-01T00:00:00Z',collected_at:'2026-01-02T00:00:00Z',coverage:'complete',value:'1.25',unit:'EA',meaning:'input'} as const;
 const refs = [source, {...source, reference:'ref-2', origin:'manual', environment:'unknown', occurred_at:null, collected_at:null}, {...source, reference:'ref-3', origin:'native', environment:'test'}, {...source, reference:'ref-4', origin:'unknown', environment:'unknown'}] as const;
 const quantity = {value:'1.25',unit:'EA',meaning:'result',origins:['manual','mock','native','unknown'],environments:['mock','test','unknown'],fact_role:'confirmed',observed_at:null,collected_at:null,coverage:'partial',source_refs:refs,input_refs:refs.map(s=>s.reference)} as const;
 await act(async()=>root.render(<QuantityValue quantity={quantity as any} value="99" unit="EA" title="需求"/>));
 expect(host.textContent).toContain('1.25 EA'); expect(host.textContent).toContain('模拟'); expect(host.textContent).toContain('手工'); expect(host.textContent).toContain('原生'); expect(host.textContent).toContain('来源待核对'); expect(host.textContent).toContain('时间待核对'); expect(host.textContent).not.toContain('ref-1');
 await act(async()=>{const details = host.querySelector('details')!; details.open = true; details.dispatchEvent(new Event('toggle')); });
 expect(host.textContent).toContain('数量性质：平台确认记录');
 expect(host.textContent).toContain('输入：1.25 EA；模拟；模拟；项目 p1；对象 receipt / r1；版本 2；系统 MES；类型 receipt；外部编号 ext；范围 site；发生 2026-01-01T00:00:00Z；读取 2026-01-02T00:00:00Z；覆盖 平台记录完整；含义 input；引用 ref-1');
 await act(async()=>{const details = host.querySelector('details')!; details.open = false; details.dispatchEvent(new Event('toggle')); });
 expect(host.textContent).not.toContain('输入：1.25 EA'); expect(host.textContent).not.toContain('ref-1');
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

it.each([['observation', '原生观察'], ['unknown', '待核对']] as const)('shows %s quantity nature in expanded evidence', async (role, label) => {
 const host=document.createElement('div'); const root=createRoot(host);
 const source={reference:'ref',project_id:'p',object_kind:'component',object_id:'c',system:'MES',source_type:'component',external_id:'c',version:1,namespace:'test',origin:'native',environment:'test',occurred_at:null,collected_at:null,coverage:'unknown',value:'2',unit:'EA',meaning:'input'} as const;
 const quantity={value:'2',unit:'EA',meaning:'result',origins:['native'],environments:['test'],fact_role:role,observed_at:null,collected_at:null,coverage:'unknown',source_refs:[source],input_refs:['ref']} as const;
 await act(async()=>root.render(<QuantityValue quantity={quantity as any} value="2" unit="EA" title="需求"/>));
 await act(async()=>{const details=host.querySelector('details')!;details.open=true;details.dispatchEvent(new Event('toggle'));});
 expect(host.textContent).toContain(`数量性质：${label}`);
 await act(async()=>root.unmount());
});
