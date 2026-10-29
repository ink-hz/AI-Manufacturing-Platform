import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, vi } from 'vitest';
import { App } from '../App';
import type { MountOptions } from '../types';
import type { ProjectDetail, ObjectSummary, WorkflowBootstrap, ObjectDetail, ObjectKind, ObjectPage, ActorTaskPage, Dashboard } from './types';
export const project: ProjectDetail = { id: '00000000-0000-4000-8000-000000000001', version: 3, name: '相机项目', line_id: '相机线', product: '相机', customer_id: '客户甲', mode: 'internal', unit: { code: '件', scale: 0 }, quantity: '2', contract: { customer_approval_required: false, customer_release_required: false, acceptance_required: true, customer_revision: 'C1', internal_revision: 'M1', material_ownership_rules: '自有' }, stages: [], summary: { original_order_quantity: '2', current_order_quantity: '2', allocated: '2', produced_good: '2', shipped: '0', signed: '0', accepted: '0', remaining_to_ship: '2', remaining_to_accept: '2' }, allowed_actions: ['demand.record', 'shipment.request'] };
export const bootstrap: WorkflowBootstrap = { protocol: 1, allowed: true, available: true, workflow_available: true, workflow_access: true, can_edit: true, release: 'test', legacy_access: false, configuration_admin: false, dataset: { id: 'test', mode: 'test', label: '独立测试' }, user: { id: '00000000-0000-4000-8000-000000000002', display_name: '李工' }, project_ids: [project.id] };
export const source = { system: 'ERP凭据', object_type: 'order_line', external_id: 'ORDER-001', version: 1, mode: 'manual' as const, occurred_at: '2026-10-28T08:00:00Z', collected_at: '2026-10-28T08:01:00Z', cutoff: null, evidence: '原始签署文件' };
export const order: ObjectSummary = { id: '00000000-0000-4000-8000-000000000003', project_id: project.id, kind: 'order_line', title: 'ORDER-001', state: 'open', quantity: '2', unit: '件', version: 1, source, blocking_reasons: ['待发运'], next_actions: ['shipment.request'] };
export async function flush() { await act(async () => { await new Promise(r => setTimeout(r, 0)); }); }
export async function workflowView(config: {
    initial?: string;
    projectContext?: boolean;
    readLedger?: (kind: ObjectKind, limit: number, offset: number, projectId?: string) => Promise<ObjectPage>;
    readTasks?: (limit: number, offset: number, projectId?: string) => Promise<ActorTaskPage>;
    conflictOnSubmit?: boolean;
    options?: Partial<MountOptions>;
    detail?: ObjectDetail;
    readObject?: (projectId: string, kind: ObjectKind, id: string) => Promise<ObjectDetail>;
    readDashboard?: () => Promise<Dashboard>;
    readProjects?: () => Promise<ProjectDetail[]>;
    readProject?: () => Promise<ProjectDetail>;
} = {}) {
    const host = document.createElement('div');
    document.body.append(host);
    const root = createRoot(host);
    const requests: {
        url: string;
        body: unknown;
    }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input, init) => {
        const url = String(input);
        const body = init?.body ? JSON.parse(String(init.body)) : undefined;
        requests.push({ url, body });
        let value: unknown = { items: [], total: 0, limit: 50, offset: 0 };
        let status = 200;
        if (url.endsWith('/projects'))
            value = { items: config.readProjects ? await config.readProjects() : [project] };
        else if (url.endsWith('/projects/' + project.id))
            value = config.readProject ? await config.readProject() : project;
        else if (/\/workflow\/objects\/[^/?]+\?/.test(url) && config.readLedger) {
            const u = new URL(url, 'http://localhost');
            value = await config.readLedger(u.pathname.split('/').at(-1) as ObjectKind, Number(u.searchParams.get('limit')), Number(u.searchParams.get('offset')), u.searchParams.get('project_id') || undefined);
        } else if (url.includes('/workflow/tasks?') && config.readTasks) {
            const u = new URL(url, 'http://localhost');
            value = await config.readTasks(Number(u.searchParams.get('limit')), Number(u.searchParams.get('offset')), u.searchParams.get('project_id') || undefined);
        } else if (url.endsWith('/dashboard'))
            value = config.readDashboard ? await config.readDashboard() : { cards: [order], counts: { order_line: 1 }, project_ids: [project.id], project_count: 1 };
        else if (url.endsWith('/handbook'))
            value = { title: '大制造数字化系统手册', markdown: '# 大制造数字化系统手册\n\n完整连续正文', release: 'test', updated_at: '2026-10-28T08:00:00Z', source_path: 'handbook.md', sha256: 'test' };
        else if (config.readObject && /\/projects\/[^/]+\/objects\/[^/]+\/[^/?]+$/.test(url)) {
            const parts=url.split('/');
            value=await config.readObject(parts.at(-4)!,parts.at(-2) as ObjectKind,parts.at(-1)!);
        } else if (url.includes('/objects/order_line/'))
            value = config.detail || { summary: order, value: { kind: 'order_line', original_quantity: '2', current_quantity: '2', unit: '件', original_due: '2026-12-01', current_due: '2026-12-01', allocated: '2', shipped: '0', signed: '0', accepted: '0', remaining_to_ship: '2', remaining_to_accept: '2', versions: [], work_order_impact: { items: [], total: 0, shown: 0, has_more: false, registered_quantity: '2' } }, relations: [], evidence: [], history: [] };
        else if (url.includes('/objects/unit?'))
            value = { items: [1, 2].map(n => ({ ...order, id: '00000000-0000-4000-8000-00000000000' + (n + 4), kind: 'unit', title: 'CAM-00' + n })), total: 2, limit: 50, offset: 0 };
        else if (url.includes('/objects/order_line?'))
            value = { items: [order], total: 1, limit: 50, offset: 0 };
        else if (url.endsWith('/commands')) {
            status = config.conflictOnSubmit ? 409 : 200;
            value = { code: 'VERSION_CONFLICT', fields: { current_version: 4 }, blocking_reasons: ['版本已经变化'] };
        }
        return new Response(JSON.stringify(value), { status });
    }));
    await act(async () => root.render(<App options={{ apiBase: '/api/v1/manufacturing', csrfToken: 'test', readOnly: false, bootstrap, ...config.options }}/>));
    await flush();
    const click = async (text: string) => { const b = [...host.querySelectorAll('button')].find(b => (b.getAttribute('aria-label') || b.textContent?.trim()) === text && !b.closest('[hidden]')); expect(b, text).toBeTruthy(); await act(async () => b!.click()); await flush(); };
    const field = async (name: string, value: string) => { const e = host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement; expect(e, name).toBeTruthy(); await act(async () => { Object.getOwnPropertyDescriptor(e.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(e, value); e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); }); };
    if (config.initial) {
        await click(config.initial);
        if (config.initial === '制造项目') await click('相机项目');
        else if (config.projectContext) { await field('所属项目筛选', project.id); await click('进入项目办理'); }
    }
    return { host, click, field, requests, rerender: async (options: Partial<MountOptions>) => { await act(async () => root.render(<App options={{ apiBase: "/api/v1/manufacturing", csrfToken: "test", readOnly: false, bootstrap, ...config.options, ...options }}/>)); await flush(); }, dispose: async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); } };
}
