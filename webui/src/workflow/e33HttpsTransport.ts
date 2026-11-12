// Private acceptance transport. Only the explicitly owned certificate and origin are trusted.
import { request } from 'node:https';
import { readFileSync } from 'node:fs';
export type E33Config = {
  clock: string; base: string; prefix: string; ca: string; project_id: string; evidence: string;
  sessions: Record<'supply'|'warehouse', { cookie: string; csrf: string; identity: { user_id: string } }>;
};
export function e33Transport(config: E33Config, actor: 'supply'|'warehouse', calls: unknown[]): typeof fetch {
  if (!/^https:\/\/127\.0\.0\.1:\d+$/.test(config.base) || config.prefix !== '/_preview/dingtalk-r1') throw Error('Owned PF loopback required');
  const ca = readFileSync(config.ca), session = config.sessions[actor];
  return async (input, init) => {
    const path = String(input);
    if (!path.startsWith(config.prefix + '/api/v1/manufacturing/workflow/')) throw Error('Outside owned workflow prefix');
    const headers = { ...Object.fromEntries(new Headers(init?.headers)), cookie: session.cookie, origin: config.base };
    return new Promise<Response>((resolve, reject) => {
      const req = request(config.base + path, { method: init?.method || 'GET', headers, ca, rejectUnauthorized: true }, response => {
        const chunks: Buffer[] = [];
        response.on('data', chunk => chunks.push(chunk));
        response.on('end', () => {
          const body = Buffer.concat(chunks).toString();
          const status = response.statusCode!;
          const safeHeaders = Object.fromEntries(Object.entries(response.headers).filter(([k]) => k !== 'set-cookie').map(([k,v]) => [k, String(v)]));
          calls.push({actor, path, method: init?.method || 'GET', request: init?.body ? JSON.parse(String(init.body)) : null, status, response: JSON.parse(body)});
          resolve(new Response(body, {status, headers: safeHeaders}));
        });
      });
      req.on('error', reject);
      const abort = () => req.destroy(new DOMException('Aborted', 'AbortError'));
      init?.signal?.addEventListener('abort', abort, {once: true});
      req.on('close', () => init?.signal?.removeEventListener('abort', abort));
      if (init?.signal?.aborted) { abort(); return; }
      if (init?.body) req.write(String(init.body));
      req.end();
    });
  };
}
