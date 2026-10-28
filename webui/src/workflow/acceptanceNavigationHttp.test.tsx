// Private E30 bridge: actual React tree + two server sessions + real HTTP CAS.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { writeFile } from 'node:fs/promises';
import { App } from '../App';
import { createWorkflowApi } from './api';

it('E30 preserves the conflicted draft, whole handbook and context, then departs exactly once', async () => {
  const base = process.env.WORKFLOW_HTTP_BASE!;
  const secret = process.env.WORKFLOW_HTTP_SECRET!;
  const projectId = process.env.WORKFLOW_PROJECT_ID!;
  expect(base).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
  const nativeFetch = globalThis.fetch;
  const calls: unknown[] = [];
  async function session(name: string) {
    const r = await nativeFetch(base + '/fixture/login', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({name, secret})});
    expect(r.status).toBe(200);
    const body = await r.json();
    return {csrf: body.csrf as string, cookie: r.headers.get('set-cookie')!.split(';')[0]};
  }
  const first = await session('owner'), second = await session('planner');
  const transport: typeof fetch = async (input, init) => {
    const r = await nativeFetch(base + String(input), {...init, headers: {...Object.fromEntries(new Headers(init?.headers)), cookie: first.cookie, origin: base}});
    calls.push({path: String(input), method: init?.method || 'GET', request: init?.body ? JSON.parse(String(init.body)) : null, status: r.status, response: await r.clone().json()});
    return r;
  };
  vi.stubGlobal('fetch', transport);
  const api = createWorkflowApi({apiBase:'/api/v1/manufacturing', csrfToken:first.csrf, readOnly:false});
  const bootstrap = await api.bootstrap(), project = await api.project(projectId), handbook = await api.handbook();
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const events: string[] = [];
  const flush = async () => act(async () => { await new Promise(r => setTimeout(r, 50)); });
  const click = async (text: string) => { const b = [...host.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || b.textContent?.trim()) === text && !b.closest('[hidden]')); expect(b, text).toBeTruthy(); await act(async () => b!.click()); await flush(); };
  const field = async (name: string, value: string) => { const e = host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement; expect(e, name).toBeTruthy(); await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(e,value); e.dispatchEvent(new Event('input',{bubbles:true})); }); };
  try {
    await act(async () => root.render(<App options={{apiBase:'/api/v1/manufacturing',csrfToken:first.csrf,readOnly:false,bootstrap,onDirtyChange:d=>events.push(String(d)),onNavigatePlatform:()=>events.push('leave')}}/>));
    await flush(); await click('制造项目'); await click(project.name); await click('登记需求');
    await field('产品','E30 retained camera draft'); await field('需求数量','2'); await field('需求交期','2026-11-04');
    await field('来源业务编号','E30-CAS-' + process.env.WORKFLOW_SEED); await field('来源凭据','Signed E30 evidence');
    const concurrent = await nativeFetch(base + `/api/v1/manufacturing/workflow/projects/${projectId}/commands`, {method:'POST',headers:{'content-type':'application/json',cookie:second.cookie,origin:base,'x-csrf-token':second.csrf},body:JSON.stringify({action:'project.stage',stage:'S1',status:'active',reason:'Second authorized editor',operation_id:crypto.randomUUID(),expected_version:project.version})});
    expect(concurrent.status).toBe(200);
    await click('保存需求');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('草稿已保留');
    expect(calls.some((c:any)=>c.status===409 && c.response.code==='VERSION_CONFLICT')).toBe(true);
    await click('制造手册');
    expect(host.textContent).toContain('大制造数字化系统手册');
    const finalHeading = handbook.markdown.split('\n').filter(line=>/^#{1,6} /.test(line)).at(-1)!.replace(/^#+ /,'').trim();
    expect(host.textContent).toContain(finalHeading);
    expect(calls.some((c:any)=>c.path.endsWith('/handbook') && c.response.markdown===handbook.markdown && c.response.sha256===handbook.sha256)).toBe(true);
    await click('返回工作区');
    expect((host.querySelector('[aria-label="产品"]') as HTMLInputElement).value).toBe('E30 retained camera draft');
    expect(host.textContent).toContain(project.name);
    await click('返回 Agent 平台'); expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    await click('放弃并离开'); await flush();
    expect(events.filter(e=>e==='leave')).toHaveLength(1);
    expect(events.at(-2)).toBe('false'); expect(events.at(-1)).toBe('leave');
    expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(0);
    expect((await api.objects(projectId,'demand')).items).toHaveLength(0);
    await writeFile(process.env.WORKFLOW_E30_EVIDENCE!, JSON.stringify({assertions:['two-authorized-editors','actual-HTTP-409','draft-retained','whole-handbook-SHA','context-restored','single-departure-no-second-dialog'],handbook_sha256:handbook.sha256,events,calls},null,2));
  } finally { await act(async()=>root.unmount()); host.remove(); vi.unstubAllGlobals(); }
}, 30000);
