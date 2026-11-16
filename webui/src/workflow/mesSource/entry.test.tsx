import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { it, expect, vi } from 'vitest';
import { WorkflowApp } from '../WorkflowApp';
import type { MountOptions } from '../../types';
vi.mock('../WorkflowHome', () => ({ WorkflowHome: () => <p>正式工作台</p> }));
vi.mock('../GlobalLedger', () => ({ GlobalLedger: () => <p>正式台账</p> }));
vi.mock('../../HandbookReader', () => ({ HandbookReader: () => null }));
it('admin with zero projects sees source browser at home execution and supply; member does not', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: unknown) => { const url = String(input); calls.push(url); return new Response(JSON.stringify(url.endsWith('/mes-source/status') ? { configured: false, can_refresh: false, source: null } : url.endsWith('/projects') ? { items: [] } : {}), { status: 200, headers: { 'content-type': 'application/json' } }); }));
    const options = { apiBase: '/api/v1/manufacturing', csrfToken: 'x', readOnly: false, bootstrap: { user: { id: 'a', display_name: 'Admin' }, configuration_admin: true, can_edit: true, allowed: true, workflow_access: true, dataset: { mode: 'production', label: '平台' }, release: {} } } as unknown as MountOptions;
    const host = document.createElement('div');
    const root = createRoot(host);
    await act(async () => root.render(<WorkflowApp options={options}/>));
    expect(host.querySelector('[aria-label="MES源工单"]')).not.toBeNull();
    for (const title of ['工单与执行', '计划与物料']) {
        await act(async () => Array.from(host.querySelectorAll('button')).find(b => b.textContent === title)!.click());
        expect(host.querySelector('[aria-label="MES源工单"]')).not.toBeNull();
        expect(host.textContent).toContain('平台正式台账');
    }
    await act(async () => root.render(<WorkflowApp options={{ ...options, bootstrap: { ...options.bootstrap!, configuration_admin: false, user: { ...options.bootstrap!.user, id: 'b' } } }}/>));
    expect(host.querySelector('[aria-label="MES源工单"]')).toBeNull();
    await act(async () => root.unmount());
    vi.unstubAllGlobals();
});
