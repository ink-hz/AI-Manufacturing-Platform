import { act } from 'react';
import { it, expect, vi } from 'vitest';
import { workflowView, bootstrap } from './testHelpers';
it('preserves the current named draft while reading the full handbook', async () => { const v = await workflowView({ initial: '制造项目' }); try {
    await v.click('登记需求');
    await v.field('产品', '未保存相机');
    await v.click('制造手册');
    expect(v.host.textContent).toContain('大制造数字化系统手册');
    await v.click('返回工作区');
    expect((v.host.querySelector('[aria-label="产品"]') as HTMLInputElement).value).toBe('未保存相机');
}
finally {
    await v.dispose();
} });
it('clears dirty notification before a single deferred host departure', async () => { const events: string[] = []; const v = await workflowView({ initial: '制造项目', options: { onDirtyChange: d => events.push(String(d)), onNavigatePlatform: () => events.push('leave') } }); try {
    await v.click('登记需求');
    await v.field('产品', '草稿');
    await v.click('返回 Agent 平台');
    expect(v.host.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    await v.click('放弃并离开');
    expect(events.at(-1)).toBe('leave');
    expect(events.at(-2)).toBe('false');
}
finally {
    await v.dispose();
} });
it('keeps a conflicted shipment draft while reading the full handbook', async () => { const v = await workflowView({ initial: '订单与交付', conflictOnSubmit: true }); try {
    await v.click('交付与关闭');
    await v.click('发货申请');
    const boxes = [...v.host.querySelectorAll('input[type="checkbox"]')] as HTMLInputElement[];
    expect(boxes).toHaveLength(2);
    await act(async () => boxes.forEach(b => b.click()));
    await v.click('提交发货申请');
    expect(v.host.querySelector('[role="alert"]')?.textContent).toContain('版本');
    await v.click('制造手册');
    expect(v.host.textContent).toContain('大制造数字化系统手册');
    await v.click('返回工作区');
    expect([...v.host.querySelectorAll('input[type="checkbox"]')].filter(b => (b as HTMLInputElement).checked)).toHaveLength(2);
}
finally {
    await v.dispose();
} });
it('retires drafts and sensitive project state when the host account changes', async () => { const auth = vi.fn(); const v = await workflowView({ initial: '制造项目', options: { onAuthError: auth } }); try {
    await v.click('登记需求');
    await v.field('产品', 'private previous account draft');
    await v.rerender({ bootstrap: { ...bootstrap, user: { ...bootstrap.user, display_name: '同一账号刷新' } } });
    expect((v.host.querySelector('[aria-label="产品"]') as HTMLInputElement).value).toBe('private previous account draft');
    await v.rerender({ bootstrap: { ...bootstrap, user: { id: '00000000-0000-4000-8000-000000000099', display_name: '另一账号' } } });
    expect(v.host.querySelector('[aria-label="产品"]')).toBeNull();
    expect(v.host.textContent).not.toContain('private previous account draft');
    expect(auth).not.toHaveBeenCalled();
}
finally {
    await v.dispose();
} });
it('failed logout remains usable and can retry once; successful logout retires', async () => {
    let finish!:()=>void;
    const logout=vi.fn().mockRejectedValueOnce(Error('offline')).mockImplementationOnce(()=>new Promise<void>(r=>{finish=r;}));
    const v=await workflowView({initial:'制造项目',options:{onLogout:logout}});
    try {
        await v.click('账户菜单'); await v.click('退出登录');
        expect(v.host.textContent).toContain('账户操作失败，请重试。');
        expect(v.host.textContent).toContain('相机项目');
        await v.click('账户菜单'); await v.click('退出登录');
        expect(logout).toHaveBeenCalledTimes(2);
        await act(async()=>finish());
        expect(v.host.textContent).not.toContain('登记需求');
    } finally {await v.dispose();}
});
it('cannot resurrect a changed identity when an old logout fails',async()=>{
 let fail!:(x:Error)=>void;const logout=vi.fn(()=>new Promise<void>((_,reject)=>fail=reject));
 const v=await workflowView({initial:'制造项目',options:{onLogout:logout}});
 try{await v.click('账户菜单');await v.click('退出登录');
 const retry=[...v.host.querySelectorAll('button')].find(b=>b.textContent==='退出登录');if(retry)await act(async()=>{retry.click();retry.click();});expect(logout).toHaveBeenCalledTimes(1);
 await v.rerender({bootstrap:{...bootstrap,user:{id:'other-identity',display_name:'New account'}}});
 await act(async()=>fail(Error('old logout failed')));
 expect(v.host.textContent).not.toContain('账户操作失败，请重试。');
 }finally{await v.dispose();}
});
