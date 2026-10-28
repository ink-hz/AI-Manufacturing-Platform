import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { startHttpHost, projectInput } from './httpTestHost';
import { EngineeringForms } from './forms/EngineeringForms';
import { SupplyForms } from './forms/SupplyForms';
import { ExecutionForms } from './forms/ExecutionForms';
import { QualityForms } from './forms/QualityForms';
import { QualityWorkspace } from './QualityWorkspace';
import { DeliveryForms } from './forms/DeliveryForms';
import { FeedbackForms } from './forms/FeedbackForms';
import { OrdersForms } from './forms/OrdersForms';
import type { CommandFields, CommandResult, ProjectDetail, WorkspaceProps, ObjectKind, ObjectSummary, DomainValue } from './types';
let http: Awaited<ReturnType<typeof startHttpHost>>, session: Awaited<ReturnType<Awaited<ReturnType<typeof startHttpHost>>['login']>>, host: HTMLDivElement, root: Root;
beforeAll(async () => { http = await startHttpHost(); session = await http.login('owner'); vi.stubGlobal('fetch', session.transport); host = document.createElement('div'); document.body.append(host); root = createRoot(host); }, 15000);
let preserveFailure=false;
afterEach(context=>{if(context.task.result?.state==='fail')preserveFailure=true;});
afterAll(async () => { if (root)
    await act(async () => root.unmount()); host?.remove(); vi.unstubAllGlobals(); if(preserveFailure)console.error(`HTTP failure fixture retained at ${http?.root}`); await http?.close(preserveFailure); });
async function field(name: string, value: string) { const e = host.querySelector(`input[aria-label="${name}"],select[aria-label="${name}"]`) as HTMLInputElement; expect(e, name).toBeTruthy(); await act(async () => { Object.getOwnPropertyDescriptor(e.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(e, value); e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); }); }
async function button(text: string) { const b = [...host.querySelectorAll('button')].find(b => b.textContent === text); expect(b, text).toBeTruthy(); await act(async () => b!.click()); }
async function check(text: string) { const l = [...host.querySelectorAll('label')].find(l => l.textContent?.includes(text) && l.querySelector('input[type="checkbox"]')); expect(l, text).toBeTruthy(); await act(async () => (l!.querySelector('input') as HTMLInputElement).click()); }
async function settle() { await act(async () => { await new Promise(r => setTimeout(r, 40)); }); }
async function submit() {
    await act(async () => { host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    // Await actual request completion, not a 40ms assumption about loopback I/O.
    await vi.waitFor(async()=>{await act(async()=>{await new Promise(r=>setTimeout(r,10));});expect(host.querySelector('form fieldset:disabled')).toBeNull();},{timeout:2000,interval:10});
}
it('submits actual named OEM forms including customer release without a viewed unit through real HTTP SQLite facts', async () => {
    const input = projectInput();
    const p = await session.api.createProject({ ...input, mode: 'oem', contract: { ...input.contract, customer_release_required: true } });
    let result: CommandResult | undefined;
    const props = async (): Promise<WorkspaceProps> => ({ api: session.api, project: await session.api.project(p.id), onChanged: r => {if (!("operation_id" in r)) throw Error("Expected command acknowledgement"); result = r;}, onDirty: () => { }, onOpen: () => { }, readOnly: false });
    await act(async () => root.render(<OrdersForms {...await props()} action="demand.record" demands={[]} orders={[]} workOrders={[]}/>));
    await field('需求数量', '2');
    await field('需求交期', '2026-12-01');
    await field('来源业务编号', 'D-HTTP');
    await field('来源凭据', 'Signed demand');
    await submit();
    expect(result, host.textContent || '').toBeDefined();
    const demand = (await session.api.objects(p.id, 'demand')).items[0];
    expect(demand.source?.object_type).toBe('demand');
    expect(demand.quantity).toBe('2');
    for (const dimension of ['technical', 'material', 'capacity', 'commercial', 'quality']) {
        result = undefined;
        await act(async () => root.render(<OrdersForms key={dimension} {...await props()} action="demand.review" demands={[demand]} orders={[]} workOrders={[]}/>));
        await field('评审需求', demand.id);
        await field('评审维度', dimension);
        await field('评审结论', 'approved');
        await field('评审凭据', 'Signed ' + dimension);
        await submit();
        expect(result, host.textContent || '').toBeDefined();
    }
    result = undefined;
    await act(async () => root.render(<OrdersForms key="order" {...await props()} action="order.register" demands={[demand]} orders={[]} workOrders={[]}/>));
    await field('订单依据需求', demand.id);
    await field('订单数量', '2');
    await field('订单交期', '2026-12-01');
    await field('来源业务编号', 'O-HTTP');
    await field('来源凭据', 'Signed order');
    await submit();
    expect(result, host.textContent || '').toBeDefined();
    expect((await session.api.objects(p.id, 'order_line')).items[0].source?.object_type).toBe('order_line');
    const allRoles = ['project_owner', 'engineering', 'planner', 'supply', 'production', 'quality', 'warehouse'];
    await session.api.grant(p.id, session.identity.user_id, { operation_id: crypto.randomUUID(), expected_version: (await session.api.project(p.id)).version, scope: { kind: 'project', project_id: p.id }, roles: allRoles, qualifications: ['inspection', 'disposition', 'quality_release', 'readiness_verification'], active: true, evidence: 'Explicit synthetic test grant' });
    const items = async (kind: ObjectKind) => (await session.api.objects(p.id, kind)).items;
    const value = async <K extends DomainValue['kind']>(kind: K, id: string) => (await session.api.object(p.id, kind, id)).value as Extract<DomainValue, {
        kind: K;
    }>;
    const cmd = async (fields: CommandFields) => session.api.command(p.id, { ...fields, expected_version: (await session.api.project(p.id)).version, operation_id: crypto.randomUUID() });
    const manual = (object_type: string, external_id = crypto.randomUUID()) => ({ system: 'fixture source', object_type, external_id, version: 1, mode: 'manual' as const, occurred_at: new Date().toISOString(), collected_at: new Date().toISOString(), cutoff: null, evidence: 'Signed fixture evidence' });
    let serial = 0;
    const form = async (component: typeof OrdersForms | typeof EngineeringForms | typeof SupplyForms | typeof ExecutionForms | typeof QualityForms | typeof DeliveryForms | typeof FeedbackForms, extra: Record<string, unknown>) => { result = undefined; const Component = component as React.ComponentType<any>; await act(async () => root.render(<Component key={++serial} {...await props()} demands={await items('demand')} orders={await items('order_line')} workOrders={await items('work_order')} revisions={await items('revision')} lots={await items('material_lot')} requirements={await items('requirement')} commitments={await items('commitment')} receipts={await items('receipt')} units={await items('unit')} tests={await items('test')} nonconformances={await items('nonconformance')} reworks={await items('rework')} interruptions={[]} plans={await items('plan')} shipments={await items('shipment')} members={(await session.api.members(p.id)).items} ecos={await items('eco')} reservations={await items('reservation')} {...extra}/>)); await settle(); };
    const fill = async (fields: Record<string, string>) => { for (const [k, v] of Object.entries(fields))
        await field(k, v); await settle(); };
    const sourceFields = async (id: string = crypto.randomUUID()) => fill({ '来源业务编号': id, '来源凭据': 'Signed actual form evidence' });
    const saved = async () => { await submit(); expect(result, host.textContent || '').toBeDefined(); const fact = await session.api.object(p.id, result!.object_type as ObjectKind, result!.object_id); expect(fact.summary).toMatchObject({ project_id: p.id, kind: result!.object_type, id: result!.object_id }); return result!; };
    await form(OrdersForms, { action: 'order.change' });
    const order = (await items('order_line'))[0];
    await fill({ '变更订单': order.id, '变更后数量': '2', '变更后交期': '2026-12-02', '变更原因': 'Customer due date change' });
    await sourceFields('O-HTTP');
    await field('来源版本', '2');
    const change = (await saved()).object_id;
    await form(OrdersForms, { action: 'order.resolve_change', change: await value('commitment_change', change), changeId: change });
    await saved();
    expect((await value('order_line', order.id)).current_due).toBe('2026-12-02');
    await form(EngineeringForms, { action: 'engineering.revision' });
    await fill({ '修订号': 'M1', '客户版本': 'C1', '内部版本': 'M1', '固件版本': 'F1', '资料名称 1': 'Camera drawing', '资料版本 1': 'M1', '资料凭据 1': 'signed drawing', '资料核对 1': 'verified', '工位 1': 'assembly', '作业指导版本 1': 'S1', '测试规范版本': 'T1', '测试程序版本': 'P1', '测量名称 1': 'voltage', '测量单位 1': 'V', '测量下限 1': '4', '测量上限 1': '6' });
    const rev = (await saved()).object_id;
    expect((await value('revision', rev)).test_spec.measurements[0].upper).toBe('6');
    await form(EngineeringForms, { action: 'engineering.handoff' });
    await fill({ '交接修订': rev, '接收系统': 'MES', '实际收到修订号': 'M1', '接收结论': 'accepted', '交接凭据': 'MES signed handoff' });
    await saved();
    await form(EngineeringForms, { action: 'work_order.register' });
    await fill({ '工单依据订单': order.id, '工单固定修订': rev, '工单数量': '2', '试产数量': '1', '计划开始': '2026-12-01T08:00', '计划结束': '2026-12-02T08:00' });
    await sourceFields('WO-HTTP');
    const wo = (await saved()).object_id;
    expect((await value('work_order', wo)).source.object_type).toBe('work_order');
    await cmd({ action: 'order.allocate', order_line_id: order.id, work_order_id: wo, quantity: '2', unit: 'piece' });
    for (const kind of ['equipment', 'people'] as const)
        await cmd({ action: 'readiness.record', work_order_id: wo, kind, reference: kind + '-HTTP', evidence: 'Current qualified readiness', decision: 'verified', valid_until: '2027-12-01T00:00:00Z' });
    await form(SupplyForms, { action: 'material.define' });
    await fill({ '物料业务编号': 'steel', '批次业务编号': 'LOT-HTTP', '批次有效期': '2027-12-01' });
    await sourceFields('LOT-HTTP');
    const lot = (await saved()).object_id;
    const plan = await cmd({ action: 'plan.receive', source: { ...manual('plan'), cutoff: new Date().toISOString() }, input_revision_ids: [rev], input_order_versions: [{ order_line_id: order.id, version: 2 }], requirements: ['trial', 'bulk'].map(execution_scope => ({ work_order_id: wo, execution_scope: execution_scope as 'trial' | 'bulk', material_id: 'steel', owner_id: 'Customer 1', quantity: '1', unit: 'kg' })) });
    const reqs = (await value('plan', plan.object_id)).requirement_ids;
    await form(SupplyForms, { action: 'supply.commit' });
    await fill({ '承诺对应需求': reqs[0], '供应承诺数量': '2', '原始承诺交期': '2026-12-01', '当前承诺交期': '2026-12-01' });
    await sourceFields('PROMISE-HTTP');
    const commitment = (await saved()).object_id;
    await form(SupplyForms, { action: 'supply.receive' });
    await fill({ '到货对应承诺': commitment, '到货物料批次': lot, '本次到货数量': '2' });
    await sourceFields('RECEIPT-HTTP');
    const receipt = (await saved()).object_id;
    await form(SupplyForms, { action: 'supply.inspect' });
    await fill({ '检验到货记录': receipt, '本次合格数量': '2', '本次拒收数量': '0', '检验凭据': 'Qualified IQC' });
    await saved();
    expect((await value('receipt', receipt)).accepted).toBe('2');
    const external = async (action: string, fields: Record<string, unknown>) => { const r = await session.transport('/fixture/authority', { method: 'POST', headers: { 'content-type': 'application/json', 'x-csrf-token': session.options.csrfToken }, body: JSON.stringify({ action, fields }) }); expect(r.status, await r.text()).toBe(200); };
    await external('receive', { project_id: p.id, external_id: 'WMS-HTTP', commitment_id: commitment, lot_id: lot, material_id: 'steel', owner_id: 'Customer 1', quantity: '2', unit: 'kg', scale: 3, expiry: '2027-12-01', external_actor: 'WMS operator', signature: 'External signed receipt' });
    await external('inspect', { project_id: p.id, external_id: 'QMS-HTTP', receipt_external_id: 'WMS-HTTP', accepted: '2', rejected: '0', external_actor: 'QMS inspector', signature: 'External signed inspection' });
    for (const req of reqs) {
        await form(SupplyForms, { action: 'reservation.request' });
        await fill({ '预留对应需求': req, '预留物料批次': lot, '请求预留数量': '1' });
        const reservation = await saved();
        await cmd({ action: 'exchange.dispatch', exchange_id: reservation.exchange_id! });
        expect((await value('exchange', reservation.exchange_id!)).phase).toBe('accepted');
    }
    await cmd({ action: 'unit.register', work_order_id: wo, sns: ['CAM-001', 'CAM-002'] });
    const units = await items('unit');
    expect(units.every(u => u.revision_id === rev)).toBe(true);
    await form(ExecutionForms, { action: 'production.start', mode: 'trial', workOrderId: wo });
    await field('开工工单', wo);
    await check('CAM-001');
    const start = await saved();
    await cmd({ action: 'exchange.dispatch', exchange_id: start.exchange_id! });
    expect((await value('unit', units[0].id)).state).toBe('running');
    const revision = await value('revision', rev);
    const execute = async (unit: ObjectSummary, rework?: string) => { await form(ExecutionForms, { action: 'execution.record', workOrderId: wo, revision }); await fill({ '执行工单': wo, '序列号': unit.title, '实际物料用量 1': '0.001' }); if (rework)
        await fill({ '独立返工单': rework, '工位': 'repair', '作业指导版本': 'RW1' }); await sourceFields(); return saved(); };
    const measure = async (unit: ObjectSummary, measured: string, rework?: string) => { await form(QualityForms, { action: 'test.record', unit: await value('unit', unit.id), revision }); await field('voltage 实测值', measured); if (rework)
        await field('独立返工单（复测）', rework); await sourceFields(); return saved(); };
    await execute(units[0]);
    const test = await measure(units[0], '5');
    expect((await value('test', test.object_id)).outcome).toBe('pass');
    await form(ExecutionForms, { action: 'first_article.record', workOrderId: wo });
    await fill({ '首件工单': wo, '试产序列号 1': units[0].id, '完整通过的测试 1': test.object_id, '首件检验单号': 'FAI-HTTP' });
    await saved();
    await form(ExecutionForms, { action: 'production.start', mode: 'bulk', workOrderId: wo });
    await field('开工工单', wo);
    await check('CAM-002');
    const bulk = await saved();
    await cmd({ action: 'exchange.dispatch', exchange_id: bulk.exchange_id! });
    expect((await value('unit', units[1].id)).state).toBe('running');
    await execute(units[1]);
    await measure(units[1], '7');
    await form(QualityForms, { action: 'nonconformance.open' });
    await fill({ '缺陷': 'High voltage', '不合格凭据': 'Measured failure' });
    await saved();
    await form(QualityForms, { action: 'nonconformance.disposition' });
    await fill({ '返工路线编号': 'RW', '返工工位 1': 'repair', '返工作业指导 1': 'RW1', '处置依据': 'Qualified route' });
    const rw = (await saved()).object_id;
    await execute(units[1], rw);
    const retest = await measure(units[1], '5', rw);
    await form(QualityForms, { action: 'rework.complete', rework: await value('rework', rw) });
    await check('repair');
    await field('通过复测', retest.object_id);
    await saved();
    expect((await value('rework', rw)).state).toBe('complete');
    for (const releaseKind of ['manufacturing', 'quality']) {
        await form(QualityForms, { action: 'release.decide', releaseKind });
        await check('CAM-001');
        await check('CAM-002');
        await field('独立签署依据', 'Independent ' + releaseKind);
        await saved();
    }
    await expect(cmd({ action: 'shipment.request', order_line_id: order.id, unit_ids: units.map(u => u.id), quantity: '2', unit: 'piece', boxes: [] })).rejects.toMatchObject({ status: 409, reasons: expect.arrayContaining([expect.stringContaining('customer approval missing for latest test')]) });
    expect((await items('shipment')).length).toBe(0);
    result = undefined;
    await act(async () => root.render(<QualityWorkspace key="oem-customer-release" {...await props()} requestLeave={f => f()}/>));
    await settle();
    await field('查看序列号', '');
    await settle();
    expect((host.querySelector('[aria-label="查看序列号"]') as HTMLSelectElement).value).toBe('');
    await button('客户放行');
    await check('CAM-001');
    await check('CAM-002');
    await fill({ '独立签署依据': 'Customer signed acceptance of measured serials', '实际客户签署人': 'Customer external QE' });
    await sourceFields('CUSTOMER-RELEASE-HTTP');
    expect(host.textContent).toContain('合同修订 C1');
    const customerRelease = await saved();
    const customerReceipt = await value('release', customerRelease.object_id);
    expect(customerReceipt).toMatchObject({ release_kind: 'customer', revision_id: rev, customer_revision: 'C1', customer_id: 'Customer 1', external_signatory: 'Customer external QE', actor_id: session.identity.user_id, method: 'manual', decision: 'approved', source: { object_type: 'customer_release', external_id: 'CUSTOMER-RELEASE-HTTP', mode: 'manual' } });
    expect(new Set(customerReceipt.unit_ids)).toEqual(new Set(units.map(u => u.id)));
    expect(customerReceipt.actor_id).not.toBe(customerReceipt.external_signatory);
    await form(DeliveryForms, { action: 'shipment.request' });
    await check('CAM-001');
    await check('CAM-002');
    const ship = await saved();
    await cmd({ action: 'exchange.dispatch', exchange_id: ship.exchange_id! });
    const shipment = (await items('shipment'))[0];
    expect((await value('shipment', shipment.id)).shipped).toBe('2');
    for (const action of ['delivery.sign', 'delivery.accept']) {
        await form(DeliveryForms, { action, shipment: await value('shipment', shipment.id) });
        await fill({ '本次实际数量': '2', '实际客户签署人': 'Customer QE' });
        await sourceFields();
        if (action === 'delivery.accept') {
            await button('添加验收问题');
            await fill({ '验收问题 1': 'Documentation followup', '责任成员 1': session.identity.user_id });
        }
        await saved();
    }
    expect((await value('shipment', shipment.id)).accepted).toBe('2');
    await form(DeliveryForms, { action: 'delivery.resolve_issue', shipment: await value('shipment', shipment.id) });
    await field('实际解决凭据', 'Delivered customer documentation');
    await saved();
    await form(DeliveryForms, { action: 'ownership.reconcile', lot: await value('material_lot', lot), lotId: lot });
    await sourceFields();
    await saved();
    expect((await value('material_lot', lot)).ownership_reconciliations?.length).toBe(1);
    for (const state of ['frozen', 'unfrozen']) {
        await form(FeedbackForms, { action: 'freeze.request', selectedUnits: [units[0].id], selectedLots: [] });
        await fill({ '申请状态': state, '冻结或解冻原因': 'Current containment ' + state });
        const freeze = await saved();
        await cmd({ action: 'exchange.dispatch', exchange_id: freeze.exchange_id! });
        expect((await value('unit', units[0].id)).freeze_confirmed).toBe(state);
        expect((await value('shipment', shipment.id)).shipped).toBe('2');
    }
    await form(EngineeringForms, { action: 'eco.open' });
    await field('旧固定版本', rev);
    await check('WO-HTTP');
    await field('变更原因', 'Assess old shipped range');
    const eco = (await saved()).object_id;
    for (const impact of (await value('eco', eco)).impacts) {
        await form(EngineeringForms, { action: 'eco.disposition' });
        await field('待处理 ECO', eco);
        await settle();
        await fill({ '受影响对象': impact.id, '处置数量': impact.quantity, '处置凭据': 'Retain actual immutable scope' });
        await saved();
    }
    await form(EngineeringForms, { action: 'eco.switch' });
    await field('待处理 ECO', eco);
    await settle();
    await fill({ '切换原工单': wo, '切换边界': 'retain_existing', '完整保留数量': '2', '切换凭据': 'Keep accepted shipped scope' });
    await saved();
    await form(EngineeringForms, { action: 'eco.close' });
    await field('待关闭 ECO', eco);
    await settle();
    await saved();
    expect((await value('eco', eco)).implementation_outcome).toBe('retained');
    await form(FeedbackForms, { action: 'rma.open', shipment: await value('shipment', shipment.id) });
    await field('客户问题事实', 'Field failure under investigation');
    await sourceFields();
    const rma = (await saved()).object_id;
    expect((await value('rma', rma)).shipment_id).toBe(shipment.id);
    let capa: string | undefined;
    for (const step of ['containment', 'root_cause', 'correction', 'verification']) {
        await form(FeedbackForms, { action: 'capa.update', step, rma: await value('rma', rma), capa: capa ? await value('capa', capa) : null });
        const name = ({ containment: '遏制', root_cause: '根因分析', correction: '纠正措施', verification: '有效性验证' } as Record<string, string>)[step];
        await fill({ [name + '说明']: 'Observed ' + step, '实际证据': 'Signed ' + step });
        if (step === 'correction')
            await fill({ '纠正措施类型': 'training', '本措施实际实施凭据': 'Completed retraining record' });
        if (step === 'verification')
            await field('有效性结果', 'pass');
        capa = (await saved()).object_id;
    }
    await form(FeedbackForms, { action: 'capa.close', capa: await value('capa', capa!) });
    await saved();
    expect((await value('capa', capa!)).state).toBe('closed');
    await form(FeedbackForms, { action: 'rma.open', shipment: await value('shipment', shipment.id) });
    await fill({ '原始已发序列号': units[1].id, '客户问题事实': 'Separate engineering feedback' });
    await sourceFields();
    const engineeringRma = (await saved()).object_id;
    let engineeringCapa: string | undefined;
    for (const step of ['containment', 'root_cause', 'correction', 'verification']) {
        await form(FeedbackForms, { action: 'capa.update', step, rma: await value('rma', engineeringRma), capa: engineeringCapa ? await value('capa', engineeringCapa) : null });
        const name = ({ containment: '遏制', root_cause: '根因分析', correction: '纠正措施', verification: '有效性验证' } as Record<string, string>)[step];
        await fill({ [name + '说明']: 'Actual ' + step, '实际证据': 'Signed ' + step });
        if (step === 'correction')
            await field('适用工程变更', eco);
        if (step === 'verification')
            await field('有效性结果', 'pass');
        engineeringCapa = (await saved()).object_id;
    }
    await form(FeedbackForms, { action: 'capa.close', capa: await value('capa', engineeringCapa!) });
    await submit();
    expect(result).toBeUndefined();
    expect(host.querySelector('[role="alert"]')).not.toBeNull();
    expect((await value('capa', engineeringCapa!)).state).toBe('open');
    expect((await value('eco', eco)).implementation_outcome).toBe('retained');
}, 60000);
it('rebases a real conflicted named draft only after reading and choosing current server facts', async () => {
    const p = await session.api.createProject(projectInput());
    let result: CommandResult | undefined;
    await act(async () => root.render(<OrdersForms key="rebase-http" api={session.api} project={await session.api.project(p.id)} action="demand.record" demands={[]} orders={[]} workOrders={[]} onChanged={r => {if (!("operation_id" in r)) throw Error("Expected command acknowledgement"); result = r;}} onOpen={() => { }} onDirty={() => { }} readOnly={false}/>));
    await field('需求数量', '2');
    await field('需求交期', '2026-12-01');
    await field('来源业务编号', 'CAS-DEMAND');
    await field('来源凭据', 'Signed CAS demand');
    await session.api.command(p.id, { action: 'project.stage', stage: 'S1', status: 'active', reason: 'Concurrent collaboration', operation_id: crypto.randomUUID(), expected_version: p.version });
    await submit();
    expect(result).toBeUndefined();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('草稿已保留');
    await button('保留草稿并对照当前资料');
    await settle();
    await button('使用当前版本继续此草稿');
    await submit();
    expect(result, host.textContent || '').toBeDefined();
    expect((await session.api.objects(p.id, 'demand')).items[0].source?.external_id).toBe('CAS-DEMAND');
});
