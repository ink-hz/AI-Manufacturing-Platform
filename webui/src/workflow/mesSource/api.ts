import type { MesStatus, MesKind, MesScope, MesObservation } from './types';
type Request = <T>(path: string, method?: string, body?: unknown, signal?: AbortSignal) => Promise<T>;
export function mesSourceApi(request: Request) {
    const path = '/material-control/mes-source';
    return {
        mesSourceStatus: (signal?: AbortSignal) => request<MesStatus>(path + '/status', 'GET', undefined, signal),
        mesSourceQuery: (kind: MesKind, scope: MesScope, refresh: boolean, signal?: AbortSignal) => request<MesObservation>(path + '/' + kind + '?' + new URLSearchParams(Object.fromEntries(Object.entries(scope).map(([k, v]) => [k, String(v)]))), refresh ? 'POST' : 'GET', undefined, signal),
    };
}
