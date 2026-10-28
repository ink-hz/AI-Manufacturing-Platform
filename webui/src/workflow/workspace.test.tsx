import { ActionForms } from './ActionForms';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { EngineeringForms } from './forms/EngineeringForms';
import { project, order } from './testHelpers';
import { it, expect, vi } from 'vitest';
import { workflowView } from './testHelpers';
it('offers nine operational workspaces with real project context and one current action', async () => {
    const v = await workflowView();
    try {
        const nav = v.host.querySelector('nav[aria-label="制造工作区"]')!;
        expect([...nav.querySelectorAll('button')].map(b => b.textContent)).toEqual(['工作台', '制造项目', '订单与交付', '计划与物料', '工单与执行', '质量与追溯', '事项', '系统协同', '制造手册']);
        await v.click('订单与交付');
        await v.click('相机项目');
        expect(v.host.textContent).toContain('待发 2');
        await v.click('登记需求');
        expect(v.host.querySelectorAll('form')).toHaveLength(1);
        expect(v.host.querySelector('textarea')).toBeNull();
    }
    finally {
        await v.dispose();
    }
});
it('drills a home card into the same owned detail and preserves manual source badge', async () => {
    const v = await workflowView();
    try {
        await v.click('ORDER-001');
        expect(v.requests.some(r => r.url.endsWith('/objects/order_line/00000000-0000-4000-8000-000000000003'))).toBe(true);
        expect(v.host.textContent).toContain('人工登记');
        expect(v.host.textContent).toContain('独立测试');
    }
    finally {
        await v.dispose();
    }
});
it('uses bounded revision family summaries without one detail read per option', async () => {
    const host = document.createElement('div'), root = createRoot(host), lookup = vi.fn(async () => { throw Error('per-option lookup forbidden'); });
    document.body.append(host);
    try {
        await act(async () => root.render(<EngineeringForms project={project} api={{ object: lookup } as any} action="engineering.revision" onOpen={() => { }} onDirty={() => { }} onChanged={() => { }} readOnly={false} orders={[]} workOrders={[]} revisions={Array.from({ length: 50 }, (_, i) => ({ ...order, id: String(i), kind: 'revision', title: 'Package ' + i, revision_family_id: 'family-' + i }))}/>));
        expect(lookup).not.toHaveBeenCalled();
        expect(host.querySelectorAll('[aria-label="资料系列"] option')).toHaveLength(51);
    }
    finally {
        await act(async () => root.unmount());
        host.remove();
    }
});
it('opens an authorized contextual action in its operational workspace', async () => {
    const v = await workflowView();
    try {
        await v.click('ORDER-001');
        await v.click('前往处理：发货申请');
        expect(v.host.textContent).toContain('当前事项：ORDER-001');
        expect(v.host.textContent).toContain('交付、所有权与独立关闭');
        expect(v.host.querySelectorAll('form')).toHaveLength(0);
    }
    finally {
        await v.dispose();
    }
});
it('preserves a stage hint draft when its disclosure is collapsed', async () => {
    const host = document.createElement('div'), root = createRoot(host);
    document.body.append(host);
    try {
        await act(async () => root.render(<ActionForms project={{ ...project, allowed_actions: ['project.stage'] }} api={{} as any} onDirty={() => { }} onChanged={() => { }} onOpen={() => { }} readOnly={false}/>));
        const details = host.querySelector('details')!;
        await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')); });
        const input = host.querySelector('[aria-label="阶段说明"]') as HTMLInputElement;
        await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Unfinished collaboration note'); input.dispatchEvent(new Event('input', { bubbles: true })); });
        await act(async () => { details.open = false; details.dispatchEvent(new Event('toggle')); });
        await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')); });
        expect((host.querySelector('[aria-label="阶段说明"]') as HTMLInputElement).value).toBe('Unfinished collaboration note');
    }
    finally {
        await act(async () => root.unmount());
        host.remove();
    }
});
