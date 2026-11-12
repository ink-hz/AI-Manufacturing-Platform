// Real WorkflowApp + private certificate-verified PF HTTPS. Ordinary UI runs never connect.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { readFileSync, writeFileSync } from 'node:fs';
import { WorkflowApp } from './WorkflowApp';
import { createWorkflowApi } from './api';
import { e33Transport, type E33Config } from './e33HttpsTransport';

it.skipIf(!process.env.WORKFLOW_E33_SESSION)('E33 records, assigns, accepts, reports and closes the same arrival through actual PF HTTPS', async () => {
  const config: E33Config = JSON.parse(readFileSync(process.env.WORKFLOW_E33_SESSION!, 'utf8'));
  vi.setSystemTime(new Date(config.clock));
  const calls: any[] = [];
  const host = document.createElement('div'); document.body.append(host);
  let root = createRoot(host);
  const flush = async () => act(async () => { await new Promise(r => setTimeout(r, 35)); });
  const wait = async (predicate: () => boolean, label: string) => {
    for (let n = 0; n < 100; n++) { if (predicate()) return; await flush(); }
    throw Error(label + ': ' + host.textContent);
  };
  const button = (text: string) => [...host.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || b.textContent?.trim()) === text && !b.closest('[hidden]'));
  const click = async (text: string) => { await wait(() => !!button(text) && !button(text)!.disabled, text); await act(async () => button(text)!.click()); await flush(); };
  const field = async (label: string, value: string) => {
    await wait(() => !!host.querySelector(`[aria-label="${label}"]`), label);
    const element = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement | HTMLSelectElement;
    const select = element instanceof HTMLSelectElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(select ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(element, value);
      element.dispatchEvent(new Event(select ? 'change' : 'input', {bubbles: true}));
    });
  };
  async function mount(actor: 'supply'|'warehouse') {
    vi.stubGlobal('fetch', e33Transport(config, actor, calls));
    const options = {apiBase:config.prefix+'/api/v1/manufacturing', csrfToken:config.sessions[actor].csrf, readOnly:false};
    const api = createWorkflowApi(options), bootstrap = await api.bootstrap();
    await act(async () => root.render(<WorkflowApp options={{...options, bootstrap}}/>));
    await flush();
    return api;
  }
  try {
    let api = await mount('supply');
    const project = await api.project(config.project_id);
    await click('制造项目'); await click(project.name); await click('供应与物料');
    await click('安排核实'); await click('记录实际包裹');
    await field('到件编号', 'E33-PACKAGE'); await field('观察位置', '收货区 A');
    await field('包裹数', '2'); await field('实物描述', '封装标签待核实'); await click('保存观察');
    await wait(() => calls.some(c=>c.request?.action==='arrival.record' && c.status===200), 'arrival command');
    const arrivalId = calls.find(c=>c.request?.action==='arrival.record' && c.status===200).response.object_id;
    await wait(() => !!host.querySelector('[aria-label="核实引用"]') || [...host.querySelectorAll('button')].some(b=>b.textContent?.includes('E33-PACKAGE')), 'saved reference');
    const referenceButton = [...host.querySelectorAll('button')].find(b=>b.textContent?.includes('E33-PACKAGE'))!;
    await act(async () => referenceButton.click()); await flush();
    await field('核实人', config.sessions.warehouse.identity.user_id); await field('核实任务说明', 'E33 核对包裹身份');
    await click('创建核实任务');
    await wait(() => calls.some(c=>c.request?.action==='material_task.open' && c.status===200), 'task command');
    const taskId = calls.find(c=>c.request?.action==='material_task.open' && c.status===200).response.object_id;
    await act(async () => root.unmount()); root = createRoot(host);
    api = await mount('warehouse');
    await click('事项');
    await wait(() => calls.some(c=>c.actor==='warehouse' && c.response?.items?.some((i:any)=>i.target?.id===taskId)), 'warehouse responsibility');
    const target = [...calls].reverse().find(c=>c.actor==='warehouse' && c.response?.items?.some((i:any)=>i.target?.id===taskId)).response.items.find((i:any)=>i.target?.id===taskId);
    expect(target.owner_id).toBe(config.sessions.warehouse.identity.user_id);
    await click(target.target.title); await click('接单');
    await click('更新进展'); await field('进展', '已查看包裹标签，正在核对身份'); await click('提交');
    await wait(() => calls.some(c=>c.request?.action==='material_task.progress' && c.status===200), 'progress');
    await click('完成任务'); await field('核实结论', 'identity_verified'); await field('完成说明', '标签与观察一致；仅确认身份'); await click('提交');
    await wait(() => calls.some(c=>c.request?.action==='material_task.close' && c.status===200), 'typed close');
    await wait(() => !!host.textContent?.includes('状态：已完成'), 'closed detail');
    const detail = await api.object(config.project_id, 'material_task', taskId);
    expect((detail.value as any).history).toHaveLength(4);
    expect(host.textContent).toContain('已查看包裹标签，正在核对身份');
    expect(host.textContent).toContain('E33-PACKAGE');
    expect(calls.filter(c=>c.request?.action==='material_task.close')[0].request.outcome).toBe('identity_verified');
    expect(calls.filter(c=>c.request?.action==='material_task.open')[0].request.requirement_id).toBeUndefined();
    writeFileSync(config.evidence, JSON.stringify({arrival_id:arrivalId, task_id:taskId, calls}, null, 2));
  } finally { writeFileSync(config.evidence + '.calls.json', JSON.stringify(calls, null, 2)); vi.useRealTimers(); await act(async()=>root.unmount()); host.remove(); vi.unstubAllGlobals(); }
}, 30000);
