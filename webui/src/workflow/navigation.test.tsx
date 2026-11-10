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
it('keeps a conflicted shipment draft while reading the full handbook', async () => { const v = await workflowView({ initial: '订单与交付', projectContext: true, conflictOnSubmit: true }); try {
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
it('restores workspace and ancestor scroll with the retained draft after handbook return',async()=>{
 vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{callback(0);return 0;});
 const v=await workflowView({initial:'制造项目'});
 try{await v.click('登记需求');await v.field('产品','带滚动的草稿');
 const frame=v.host.querySelector('.mf-root') as HTMLElement;v.host.scrollTop=250;frame.scrollTop=130;
 await v.click('制造手册');v.host.scrollTop=0;frame.scrollTop=0;await v.click('返回工作区');
 expect(v.host.scrollTop).toBe(250);expect(frame.scrollTop).toBe(130);expect((v.host.querySelector('[aria-label="产品"]') as HTMLInputElement).value).toBe('带滚动的草稿');
 }finally{await v.dispose();}
});
it('sidebar selection leaves handbook for global records while the explicit return retains work',async()=>{
 const v=await workflowView({initial:'订单与交付',projectContext:true});
 try{await v.click('制造手册');await v.click('订单与交付');expect(v.host.querySelector('[aria-label="所属项目筛选"]')).not.toBeNull();expect(v.host.querySelectorAll('form')).toHaveLength(0);}finally{await v.dispose();}
});
it('retains account-menu keyboard focus and sidebar drawer focus in the current product',async()=>{
 const v=await workflowView({options:{onLogout:async()=>{},onNavigatePlatform:()=>{}}});
 try{const account=v.host.querySelector('[aria-label="账户菜单"]') as HTMLButtonElement;
 await act(async()=>{account.focus();account.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));});expect(document.activeElement?.getAttribute('role')).toBe('menuitem');
 await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));expect(v.host.querySelector('[role="menu"]')).toBeNull();expect(document.activeElement).toBe(account);
 await v.click('收起侧栏');expect(v.host.querySelector('[aria-label="展开侧栏"]')).not.toBeNull();
 const toggle=v.host.querySelector('[aria-label="打开导航"]') as HTMLButtonElement;
 await act(async()=>{toggle.focus();toggle.click();});expect(v.host.querySelector('[role="dialog"][aria-label="制造导航"]')).not.toBeNull();
 await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));expect(v.host.querySelector('[role="dialog"][aria-label="制造导航"]')).toBeNull();expect(document.activeElement).toBe(toggle);
 }finally{await v.dispose();}
});
it('traps navigation drawer focus and closes it after opening the business ledger',async()=>{
 const v=await workflowView();try{await v.click('打开导航');const dialog=v.host.querySelector('[role="dialog"][aria-label="制造导航"]')!;
 expect(dialog.querySelector('.mf-console-collapse')).toBeNull();const buttons=[...dialog.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
 await act(async()=>{buttons.at(-1)!.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));});expect(document.activeElement).toBe(buttons[0]);
 await v.click('订单与交付');expect(v.host.querySelector('[role="dialog"][aria-label="制造导航"]')).toBeNull();expect(v.host.querySelector('[aria-label="所属项目筛选"]')).not.toBeNull();expect(document.body.style.overflow).not.toBe('hidden');
 }finally{await v.dispose();}
});
it('revocation retires a pending account departure and removes private user and draft state',async()=>{
 const onNavigatePlatform=vi.fn(),onLogout=vi.fn();
 const v=await workflowView({initial:'制造项目',options:{user:{displayName:'私人姓名',roleLabel:'成员'},onNavigatePlatform,onLogout}});
 try{await v.click('登记需求');await v.field('产品','私有草稿');await v.click('返回 Agent 平台');
 const original=fetch;vi.stubGlobal('fetch',vi.fn(async(input,init)=>String(input).endsWith('/dashboard')?new Response('{}',{status:403}):original(input,init)));
 await v.rerender({csrfToken:'rotated'});expect(v.host.textContent).toContain('无权访问');expect(v.host.textContent).not.toContain('私人姓名');expect(v.host.textContent).not.toContain('私有草稿');expect(v.host.querySelector('[role="dialog"]')).toBeNull();expect(onNavigatePlatform).not.toHaveBeenCalled();expect(onLogout).not.toHaveBeenCalled();
 }finally{await v.dispose();}
});
it('opens production management independently from the controlled test and calibration ledger',async()=>{
 const v=await workflowView({options:{bootstrap:{...bootstrap,configuration_admin:true,project_ids:[]}},readProjects:async()=>[]});
 try{expect(v.host.querySelector('.mf-badge')?.textContent).toContain('独立测试');const original=fetch;vi.stubGlobal('fetch',vi.fn(async(input,init)=>String(input).endsWith('/production-tools/status')?new Response(JSON.stringify({configured:true,source_namespace:'native',source_project_id:null,capabilities:{}})):String(input).endsWith('/production-tools/projects')?new Response(JSON.stringify({items:[{id:'99999999999999999999',name:'真实源项目'}],limit:100,has_more:false,next_before_id:null})):original(input,init)));
 await v.click('产测管理');expect(v.host.querySelector('.mf-badge')?.textContent).toBe('产测源数据 · 只读查询');expect(v.host.querySelector('.mf-badge')?.textContent).not.toContain('隔离测试数据');expect(v.host.textContent).toContain('真实源项目');expect(v.host.querySelector('select[aria-label="源项目"]')).not.toBeNull();
 for(const label of ['SN 观测','软件与配置目录','日志证据','记录统计']) expect([...v.host.querySelectorAll('button')].some(b=>b.textContent===label)).toBe(true);
 expect(v.host.textContent).toContain('请选择源项目');
 await v.click('测试与标定');expect(v.host.querySelector('[aria-label="所属项目筛选"]')).not.toBeNull();expect(v.host.textContent).toContain('测试计划');
 expect(v.host.querySelector('select[aria-label="源项目"]')).toBeNull();expect(v.host.querySelector('.mf-badge')?.textContent).toContain('独立测试');
 }finally{await v.dispose();}
});
it('hides production management and makes no native source requests for ordinary members',async()=>{
 const v=await workflowView({initial:'制造项目'});
 try{expect([...v.host.querySelectorAll('button')].filter(b=>b.textContent==='产测管理')).toHaveLength(0);expect(v.requests.some(r=>r.url.includes('/production-tools'))).toBe(false);}
 finally{await v.dispose();}
});
