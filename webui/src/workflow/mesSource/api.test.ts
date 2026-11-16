import { it, expect, vi } from 'vitest';
import { mesSourceApi } from './api';
it('sends exact encoded source scopes with empty POST body', async () => {
    const request = vi.fn(async <T,>() => ({} as T));
    const api = mesSourceApi(request as Parameters<typeof mesSourceApi>[0]);
    const signal = new AbortController().signal;
    await api.mesSourceQuery('orders', { prefix: 'SO', after: '' }, false, signal);
    expect(request).toHaveBeenLastCalledWith('/material-control/mes-source/orders?prefix=SO&after=', 'GET', undefined, signal);
    await api.mesSourceQuery('priority', { shop_order: 'SO1', material: 'M&1', page: 2 }, true, signal);
    expect(request).toHaveBeenLastCalledWith('/material-control/mes-source/priority?shop_order=SO1&material=M%261&page=2', 'POST', undefined, signal);
});
