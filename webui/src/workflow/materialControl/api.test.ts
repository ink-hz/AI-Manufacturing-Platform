import { expect, it, vi } from 'vitest';
import { materialControlApi } from './api';
it('sends the whole-project scope before pagination', async () => {
  const request = vi.fn().mockResolvedValue({});
  await materialControlApi(request).materialProject('p', 50, 50, undefined, {search:'轴 承', problem:'pending_iqc', work_order_id:'w/1'});
  expect(request).toHaveBeenCalledWith('/projects/p/material-control?limit=50&offset=50&search=%E8%BD%B4+%E6%89%BF&problem=pending_iqc&work_order_id=w%2F1','GET',undefined,undefined);
});
