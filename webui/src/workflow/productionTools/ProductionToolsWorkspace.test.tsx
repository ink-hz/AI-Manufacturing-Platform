import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { createWorkflowApi } from '../api';
import { flush } from '../testHelpers';
import { ProductionToolsWorkspace } from './ProductionToolsWorkspace';
const project = { id: '99999999999999999999', name: '源项目 A' };
const other = { id: '9007199254740993', name: '源项目 B' };
const directory = { items: [project, other], limit: 100, has_more: false, next_before_id: null };
const kinds = ['production', 'stopover', 'software', 'software_versions', 'configs', 'config_versions', 'review_orders', 'evidence', 'production_statistics', 'stopover_statistics', 'evidence_content'];
const status = { source_namespace: 'native', source_project_id: project.id, configured: true, capabilities: Object.fromEntries(kinds.map(k => [k, { available: true, reason: null }])) };
function page(
    items: Record<string, unknown>[] = [{ sn: 'SN-1', status: '1' }],
    extra: Record<string, unknown> = {},
) {
    return {
        snapshot_id: 'snap',
        source_namespace: 'native', source_project_id: project.id,
        source_kind: 'production',
        captured_at: '2026-11-10T00:00:00Z',
        expires_at: '2026-11-11T00:00:00Z',
        items,
        filters: {
            kind: 'production',
            start: '2026-11-09T00:00:00Z',
            end: '2026-11-10T00:00:00Z',
        },
        complete: true,
        truncation_reason: null,
        next_before_id: null,
        redacted_fields: [],
        captured_count: items.length,
        offset: 0,
        limit: 50,
        has_more: false,
        ...extra,
    };
}
afterEach(() => vi.unstubAllGlobals());
async function view(read: (url: URL, init?: RequestInit) => Promise<Response> | Response = () => new Response(JSON.stringify(page())), initial = project.id, directoryRead: (url: URL, init?: RequestInit) => Promise<Response> | Response = () => new Response(JSON.stringify(directory)), globalStatus = status) {
    const requests: {
        url: URL;
        init?: RequestInit;
    }[] = [];
    vi.stubGlobal('fetch', vi.fn((input, init) => {
        const url = new URL(String(input), location.origin);
        requests.push({ url, init });
        return url.pathname.endsWith('/status') ? Promise.resolve(new Response(JSON.stringify(url.pathname.endsWith('/production-tools/status') ? {...globalStatus, source_project_id: null} : status))) : url.pathname.endsWith('/production-tools/projects') ? Promise.resolve(directoryRead(url, init)) : Promise.resolve(read(url, init));
    }));
    const api = createWorkflowApi({ apiBase: '/api/v1/manufacturing', csrfToken: 'csrf', readOnly: false });
    const host = document.createElement('div');
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => root.render(<ProductionToolsWorkspace api={api}/>));
    await flush();
    const click = async (label: string) => {
        const b = [...host.querySelectorAll('button')].find(b => b.textContent === label);
        expect(b, label).toBeTruthy();
        await act(async () => b!.click());
        await flush();
    };
    const field = async (label: string, value: string) => {
        const e = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
        expect(e, label).toBeTruthy();
        await act(async () => {
            Object.getOwnPropertyDescriptor(e.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(e, value);
            e.dispatchEvent(new Event('input', { bubbles: true }));
            e.dispatchEvent(new Event('change', { bubbles: true }));
        });
        await flush();
    };
    if (initial && host.querySelector('[aria-label="源项目"]')) await field('源项目', initial);
    return {
        host, requests, click, field,
        dispose: async () => {
            await act(async () => root.unmount());
            api.dispose();
            host.remove();
        },
    };
}
it('loads source names without manufacturing projects and ignores an unknown selection', async () => {
    const v = await view(undefined, 'unknown');
    try {
        expect(v.host.textContent).toContain('请选择源项目');
        expect(v.host.textContent).toContain('源项目 A');
        expect(v.requests.map(r => r.url.pathname)).toEqual(['/api/v1/manufacturing/workflow/production-tools/status', '/api/v1/manufacturing/workflow/production-tools/projects']);
    } finally {
        await v.dispose();
    }
});

it('preserves duplicate SN records and discloses a bounded QuestDB capture', async () => {
    const v = await view(() => new Response(JSON.stringify(page([{ sn: 'DUPLICATE', status: '1' }, { sn: 'DUPLICATE', status: '2' }], { complete: false, truncation_reason: 'row_limit' }))));
    try {
        expect(v.host.querySelectorAll('tbody tr')).toHaveLength(2);
        expect(v.host.textContent).toContain('仅显示部分记录，请缩小时间范围或指定 SN');
        expect(v.host.textContent).toContain('缩小范围重新查询');
        expect(v.host.textContent).not.toContain('继续读取源记录');
        expect(v.host.textContent).toContain('采集时间');
    } finally {
        await v.dispose();
    }
});

it('clears and aborts obsolete project reads even when the transport resolves late', async () => {
    let finish!: (r: Response) => void;
    let signal: AbortSignal | null | undefined;
    const v = await view((url, init) => url.pathname.includes(project.id) ? new Promise(r => {
        finish = r;
        signal = init?.signal;
    }) : new Response(JSON.stringify(page([{ sn: 'B-ONLY' }]))));
    try {
        await v.field('源项目', other.id);
        expect(signal?.aborted).toBe(true);
        expect(v.host.textContent).toContain('B-ONLY');
        await act(async () => finish(new Response(JSON.stringify(page([{ sn: 'A-SECRET' }])))));
        await flush();
        expect(v.host.textContent).not.toContain('A-SECRET');
        expect(v.host.textContent).toContain('B-ONLY');
    } finally {
        await v.dispose();
    }
});

it('keeps controls and offers explicit retry on source failure without zero counts', async () => {
    let fail = true;
    const v = await view(() => fail ? new Response(JSON.stringify({ code: 'SOURCE_UNAVAILABLE' }), { status: 503 }) : new Response(JSON.stringify(page([]))));
    try {
        expect(v.host.querySelector('[role="alert"]')?.textContent).toContain('数据源暂不可用');
        expect(v.host.textContent).not.toContain('捕获记录 0');
        expect(v.host.querySelector('[aria-label="精确 SN"]')).not.toBeNull();
        fail = false;
        await v.click('重试读取产测数据');
        expect(v.host.textContent).toContain('当前范围暂无记录');
    } finally {
        await v.dispose();
    }
});

it('does not query unconfigured or unavailable capabilities', async () => {
    const v = await view();
    try {
        const query = vi.fn(async (_url: string) => new Response(JSON.stringify({ project_id: other.id, configured: false, capabilities: status.capabilities })));
        vi.stubGlobal('fetch', query);
        await v.field('源项目', other.id);
        expect(v.host.textContent).toContain('尚未配置产测数据源');
        expect(query).toHaveBeenCalledOnce();
        expect(String(query.mock.calls[0][0])).toContain('/status');
    } finally {
        await v.dispose();
    }
});

it('pages immutable snapshots and clears previous rows on revoked project access', async () => {
    const v = await view(url => url.pathname.includes('/snapshots/') ? new Response(JSON.stringify({ code: 'PROJECT_NOT_FOUND' }), { status: 404 }) : new Response(JSON.stringify(page([{ sn: 'PRIVATE-ROW' }], { captured_count: 60, has_more: true }))));
    try {
        await v.click('下一页快照');
        expect(v.requests.at(-1)?.url.pathname).toContain('/snapshots/snap');
        expect(v.requests.at(-1)?.url.searchParams.get('offset')).toBe('50');
        expect(v.host.textContent).not.toContain('PRIVATE-ROW');
        expect(v.host.textContent).toContain('源项目不存在或已移除');
    } finally {
        await v.dispose();
    }
});

it('uses snapshot previous/next offsets and preserves capture metadata', async () => {
    const v = await view(url => new Response(JSON.stringify(page([{ sn: url.searchParams.get('offset') === '50' ? 'SECOND' : 'FIRST' }], { captured_count: 60, has_more: url.searchParams.get('offset') !== '50', offset: Number(url.searchParams.get('offset') || 0) }))));
    try {
        await v.click('下一页快照');
        expect(v.host.textContent).toContain('SECOND');
        await v.click('上一页快照');
        expect(v.host.textContent).toContain('FIRST');
        expect(v.requests.at(-1)?.url.searchParams.get('offset')).toBe('0');
    } finally {
        await v.dispose();
    }
});

it('supports all catalogs with parent and explicit fresh keyset continuation', async () => {
    const v = await view(url => new Response(JSON.stringify(page([{ id: '20', name: 'catalog row' }], { source_kind: url.pathname.split('/').at(-1), complete: false, next_before_id: '20' }))));
    try {
        await v.click('软件与配置目录');
        const select = v.host.querySelector('[aria-label="目录类型"]')!;
        expect(select.querySelectorAll('option')).toHaveLength(5);
        await v.field('目录类型', 'software_versions');
        await v.field('父记录 ID', '7');
        await v.click('查询产测数据');
        expect(v.requests.at(-1)?.url.searchParams.get('parent_id')).toBe('7');
        expect(v.requests.at(-1)?.url.searchParams.has('start')).toBe(false);
        await v.click('继续读取源记录');
        expect(v.requests.at(-1)?.url.searchParams.get('before_id')).toBe('20');
        expect(v.requests.at(-1)?.url.searchParams.get('parent_id')).toBe('7');
        await v.field('目录类型', 'config_versions');
        expect(v.requests.at(-1)?.url.pathname).toContain('/catalog/config_versions');
    } finally {
        await v.dispose();
    }
});

it('renders escaped metadata and only protected evidence links', async () => {
    const v = await view(() => new Response(JSON.stringify(page([{ id: '12', csn: '<script>alert(1)</script>', url: 'https://private.invalid/file' }], { source_kind: 'evidence' }))));
    try {
        await v.click('日志证据');
        const link = v.host.querySelector('tbody a')!;
        expect(link.getAttribute('href')).toBe(`/api/v1/manufacturing/workflow/production-tools/projects/${project.id}/evidence/12/content`);
        expect(v.host.querySelector('script')).toBeNull();
        expect(v.host.textContent).toContain('<script>alert(1)</script>');
        expect(v.host.querySelector('a[href^="https:"]')).toBeNull();
    } finally {
        await v.dispose();
    }
});

it('displays server statistics with nullable ratio and never calculates from observations', async () => {
    const v = await view(() => new Response(JSON.stringify(page([{ records: 0, distinct_sn: 0, pass_records: 0, fail_records: 0, unknown_records: 0, record_pass_ratio: null, consistency: 'single_query' }], { source_kind: 'production_statistics' }))));
    try {
        await v.click('记录统计');
        expect(v.requests.at(-1)?.url.pathname).toContain('/statistics');
        expect(v.host.textContent).toContain('记录 PASS 比例');
        expect(v.host.textContent).toContain('不适用');
        expect(v.host.textContent).not.toContain('NaN');
        expect(v.host.textContent).not.toContain('FPY');
    } finally {
        await v.dispose();
    }
});

it('submits UTC exact filters and rejects invalid ranges before reading', async () => {
    const v = await view();
    try {
        await v.field('开始时间', '2026-10-01T00:00');
        await v.field('结束时间', '2026-11-10T00:00');
        const count = v.requests.length;
        await v.click('查询产测数据');
        expect(v.requests).toHaveLength(count);
        expect(v.host.textContent).toContain('31 天');
        await v.field('开始时间', '2026-11-09T00:00');
        await v.field('精确 SN', 'SN & one');
        await v.click('查询产测数据');
        expect(v.requests.at(-1)?.url.searchParams.get('start')).toBe(new Date('2026-11-09T00:00').toISOString());
        expect(v.requests.at(-1)?.url.searchParams.get('sn')).toBe('SN & one');
    } finally {
        await v.dispose();
    }
});

it('clears pending observation data on tab and submitted-filter changes', async () => {
    let finish!: (r: Response) => void;
    const v = await view(url => url.pathname.endsWith('/observations') && !url.searchParams.has('sn') ? new Promise(r => finish = r) : new Response(JSON.stringify(page([{ sn: 'CURRENT' }]))));
    try {
        await v.field('精确 SN', 'CURRENT');
        await v.click('查询产测数据');
        await act(async () => finish(new Response(JSON.stringify(page([{ sn: 'OLD' }])))));
        await flush();
        expect(v.host.textContent).not.toContain('OLD');
        await v.click('软件与配置目录');
        expect(v.host.querySelector('button[aria-pressed="true"]')?.textContent).toBe('软件与配置目录');
    } finally {
        await v.dispose();
    }
});

it('does not query a missing backend capability or mistake configuration for health', async () => {
    const v = await view();
    try {
        const calls = vi.fn(async (_url: string) => new Response(JSON.stringify({ ...status, project_id: other.id, capabilities: { ...status.capabilities, production: { available: false, reason: 'SOURCE_UNAVAILABLE' } } })));
        vi.stubGlobal('fetch', calls);
        await v.field('源项目', other.id);
        expect(calls).toHaveBeenCalledOnce();
        expect(v.host.textContent).toContain('当前数据类型尚未配置可用能力');
        expect(v.host.textContent).toContain('不代表实时连通状态');
    } finally {
        await v.dispose();
    }
});

it('renders the server aggregate counts and record ratio', async () => {
    const v = await view(() => new Response(JSON.stringify(page([{ records: 8, distinct_sn: 3, pass_records: 2, fail_records: 4, unknown_records: 2, record_pass_ratio: 0.25, consistency: 'single_query' }]))));
    try {
        await v.click('记录统计');
        expect(v.host.textContent).toContain('25.00%');
        const dl = v.host.querySelector('dl')!;
        expect(dl.textContent).toContain('记录总数8');
        expect(dl.textContent).toContain('非空 SN 数3');
    } finally {
        await v.dispose();
    }
});

it('aborts a pending query on tab change and cannot restore its rows', async () => {
    let finish!: (r: Response) => void;
    let signal: AbortSignal | null | undefined;
    const v = await view((url, init) => url.pathname.endsWith('/observations') ? new Promise(r => {
        finish = r;
        signal = init?.signal;
    }) : new Response(JSON.stringify(page([{ name: 'SOFTWARE-CURRENT' }], { source_kind: 'software' }))));
    try {
        await v.click('软件与配置目录');
        expect(signal?.aborted).toBe(true);
        await act(async () => finish(new Response(JSON.stringify(page([{ sn: 'OLD-TAB-SECRET' }])))));
        await flush();
        expect(v.host.textContent).not.toContain('OLD-TAB-SECRET');
        expect(v.host.textContent).toContain('SOFTWARE-CURRENT');
    } finally {
        await v.dispose();
    }
});

it('keeps controls and scrollable tables keyboard-accessible at a narrow viewport', async () => {
    vi.stubGlobal('innerWidth', 375);
    const v = await view();
    try {
        const select = v.host.querySelector('[aria-label="源项目"]') as HTMLSelectElement;
        await act(async () => select.focus());
        expect(document.activeElement).toBe(select);
        const region = v.host.querySelector('[aria-label="产测记录表"]') as HTMLElement;
        expect(region.tabIndex).toBe(0);
        await act(async () => region.focus());
        expect(document.activeElement).toBe(region);
        expect(v.host.querySelector('[aria-label="开始时间"]')?.closest('label')).not.toBeNull();
        for (const button of v.host.querySelectorAll('.wf-production-tabs button'))
            expect(button.getAttribute('type')).toBe('button');
    } finally {
        await v.dispose();
    }
});

it('keeps twenty-digit parent filters and adjacent large source cursors exact', async () => {
    const maximum = '99999999999999999999';
    const cursor = '9007199254740993';
    const v = await view(url => new Response(JSON.stringify(page([{ id: url.searchParams.has('before_id') ? '9007199254740992' : cursor, name: 'exact source row' }], { source_kind: 'software_versions', complete: false, next_before_id: cursor }))));
    try {
        await v.click('软件与配置目录');
        await v.field('目录类型', 'software_versions');
        await v.field('父记录 ID', maximum);
        await v.click('查询产测数据');
        expect(v.requests.at(-1)?.url.searchParams.get('parent_id')).toBe(maximum);
        await v.click('继续读取源记录');
        expect(v.requests.at(-1)?.url.searchParams.get('before_id')).toBe(cursor);
        expect(v.requests.at(-1)?.url.searchParams.get('parent_id')).toBe(maximum);
        expect(v.host.querySelector('tbody td')?.textContent).toBe('9007199254740992');
        const count = v.requests.length;
        await v.field('父记录 ID', '100000000000000000000');
        await v.click('查询产测数据');
        expect(v.requests).toHaveLength(count);
        expect(v.host.textContent).toContain('父记录 ID 必须是有效正整数');
    } finally {
        await v.dispose();
    }
});

it('uses exact large evidence IDs and displays large aggregate counts as text', async () => {
    const maximum = '99999999999999999999';
    const v = await view(url => new Response(JSON.stringify(page(url.pathname.endsWith('/statistics')
        ? [{ records: maximum, distinct_sn: '9007199254740993', pass_records: maximum,
                fail_records: 0, unknown_records: 0, record_pass_ratio: 1, consistency: 'single_query' }]
        : [{ id: maximum, csn: 'EXACT-EVIDENCE' }], { source_kind: url.pathname.endsWith('/statistics') ? 'production_statistics' : 'evidence' }))));
    try {
        await v.click('日志证据');
        expect(v.host.querySelector('tbody a')?.getAttribute('href')).toBe(`/api/v1/manufacturing/workflow/production-tools/projects/${project.id}/evidence/${maximum}/content`);
        await v.click('记录统计');
        expect(v.host.querySelector('dl')?.textContent).toContain(`记录总数${maximum}`);
        expect(v.host.querySelector('dl')?.textContent).toContain('非空 SN 数9007199254740993');
        expect(v.host.textContent).toContain('100.00%');
    } finally {
        await v.dispose();
    }
});

it('loads the source directory only on explicit continuation with exact cursors', async () => {
    const cursor = '9007199254740993';
    const v = await view(undefined, '', url => new Response(JSON.stringify(url.searchParams.has('before_id') ? {items: [other], limit: 100, has_more: false, next_before_id: null} : {items: [project], limit: 100, has_more: true, next_before_id: cursor})));
    try {
        expect(v.requests.filter(r => r.url.pathname.endsWith('/projects'))).toHaveLength(1);
        expect(v.host.textContent).not.toContain('源项目 B');
        await v.click('读取更多源项目');
        expect(v.requests.at(-1)?.url.searchParams.get('before_id')).toBe(cursor);
        expect(v.host.textContent).toContain('源项目 B');
        expect(v.host.textContent).not.toContain('读取更多源项目');
    } finally { await v.dispose(); }
});

it('distinguishes global unconfigured, failed source directory, empty directory and forbidden access', async () => {
    const scenarios = [
        {global: {...status, configured: false}, response: new Response('{}'), text: '尚未配置产测数据源', requests: 1},
        {global: status, response: new Response('{}', {status: 503}), text: '源项目目录暂不可用', requests: 2},
        {global: status, response: new Response(JSON.stringify({...directory, items: []})), text: '源项目目录暂无项目', requests: 2},
        {global: status, response: new Response('{}', {status: 403}), text: '无权访问产测管理', requests: 2},
    ];
    for (const scenario of scenarios) {
        const v = await view(undefined, '', () => scenario.response, scenario.global);
        try { expect(v.host.textContent).toContain(scenario.text); expect(v.requests).toHaveLength(scenario.requests); }
        finally { await v.dispose(); }
    }
});

it('cannot restore directory choices after unmount when transport ignores cancellation', async () => {
    let finish!: (r: Response) => void;
    let signal: AbortSignal | null | undefined;
    const v = await view(undefined, '', (_url, init) => new Promise(r => { finish = r; signal = init?.signal; }));
    await v.dispose();
    expect(signal?.aborted).toBe(true);
    await act(async () => finish(new Response(JSON.stringify(directory))));
    expect(v.requests).toHaveLength(2);
});

it('sends the selected exact source ID on every scoped tab and supports device filters', async () => {
    const v = await view();
    try {
        await v.field('精确设备', 'device & one');
        await v.click('查询产测数据');
        expect(v.requests.at(-1)?.url.searchParams.get('device')).toBe('device & one');
        for (const label of ['软件与配置目录', '日志证据', '记录统计']) {
            await v.click(label);
            if (label === '日志证据') expect(v.requests.at(-1)?.url.searchParams.has('device')).toBe(false);
            if (label === '记录统计') expect(v.requests.at(-1)?.url.searchParams.get('device')).toBe('device & one');
        }
        for (const r of v.requests.filter(r => !r.url.pathname.endsWith('/projects') && !r.url.pathname.endsWith('/production-tools/status'))) {
            expect(r.url.pathname).toContain(`/production-tools/projects/${project.id}/`);
        }
    } finally { await v.dispose(); }
});

it('refreshes the directory and ignores an obsolete continuation response', async () => {
    let finish!: (r: Response) => void;
    let signal: AbortSignal | null | undefined;
    let refreshed = false;
    const v = await view(undefined, project.id, (url, init) => {
        if (url.searchParams.has('before_id')) return new Promise(r => {finish = r; signal = init?.signal;});
        return new Response(JSON.stringify(refreshed ? {...directory, items: []} : {...directory, items: [project], has_more: true, next_before_id: other.id}));
    });
    try {
        expect(v.host.textContent).toContain('SN-1');
        await v.click('读取更多源项目');
        refreshed = true;
        await v.click('刷新源项目目录');
        expect(signal?.aborted).toBe(true);
        expect(v.host.textContent).not.toContain('SN-1');
        expect(v.host.textContent).not.toContain('源项目 A');
        await act(async () => finish(new Response(JSON.stringify({...directory, items: [other]}))));
        await flush();
        expect(v.host.textContent).not.toContain('源项目 B');
        expect(v.host.textContent).toContain('源项目目录暂无项目');
    } finally { await v.dispose(); }
});

it('retires old source rows when a refreshed configuration becomes unavailable', async () => {
    const v = await view(undefined, project.id, () => new Response(JSON.stringify({...directory, has_more:true, next_before_id:other.id})));
    try {
        vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({...status, configured:false}))));
        await v.click('读取更多源项目');
        expect(v.host.textContent).toContain('尚未配置产测数据源');
        expect(v.host.textContent).not.toContain('SN-1');
        expect(v.host.querySelector('select')?.value).toBe('');
    } finally { await v.dispose(); }
});

it('retries a failed directory continuation at the same exact cursor while retaining selection', async () => {
    const cursor = '9007199254740993';
    let attempts = 0;
    const v = await view(undefined, project.id, url => {
        if (!url.searchParams.has('before_id')) return new Response(JSON.stringify({...directory, items:[project], has_more:true, next_before_id:cursor}));
        attempts++;
        return attempts === 1 ? new Response('{}', {status:503}) : new Response(JSON.stringify({...directory, items:[other]}));
    });
    try {
        await v.click('读取更多源项目');
        expect(v.host.textContent).toContain('源项目目录暂不可用');
        expect(v.host.querySelector('select')?.value).toBe(project.id);
        expect(v.host.textContent).toContain('SN-1');
        await v.click('读取更多源项目');
        expect(attempts).toBe(2);
        expect(v.requests.filter(r => r.url.searchParams.has('before_id')).map(r => r.url.searchParams.get('before_id'))).toEqual([cursor, cursor]);
        expect(v.host.textContent).toContain('源项目 A');
        expect(v.host.textContent).toContain('源项目 B');
        expect(v.host.querySelector('select')?.value).toBe(project.id);
        expect(v.host.textContent).toContain('SN-1');
        expect(v.host.textContent).not.toContain('源项目目录暂不可用');
    } finally { await v.dispose(); }
});
