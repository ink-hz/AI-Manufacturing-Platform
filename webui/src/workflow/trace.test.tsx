import { it, expect } from 'vitest';
import { workflowView } from './testHelpers';
it('opens real quality and trace operations from the daily navigation', async () => { const v = await workflowView({ initial: '质量与追溯' }); try {
    await v.click('追溯与反馈');
    expect(v.host.querySelector('[aria-label="追溯序列号"]')).not.toBeNull();
    expect(v.host.textContent).toContain('通过实际序列号');
    expect(v.host.textContent).toContain('独立测试');
}
finally {
    await v.dispose();
} });
