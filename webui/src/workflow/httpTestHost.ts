// Test-only real HTTP transport. Business request bodies pass through unchanged.
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { createWorkflowApi } from './api';
import type { CommandFields, ProjectCreate, WorkflowCommand } from './types';
export async function startHttpHost() {
    const root = await mkdtemp(join(tmpdir(), 'workflow-http-'));
    const secret = randomUUID();
    await writeFile(join(root, 'fixture.json'), JSON.stringify({ secret }), { mode: 0o600 });
    const cwd = resolve(process.cwd(), '..');
    const python = process.env.WORKFLOW_TEST_PYTHON || '/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python';
    const child = spawn(python, ['tests/workflow/http_fixture.py', root], { cwd, env: { ...process.env, PYTHONPATH: resolve(cwd, 'src') }, stdio: ['ignore', 'pipe', 'pipe'] });
    let errors = '';
    child.stderr.on('data', b => errors += String(b));
    const nativeFetch = globalThis.fetch;
    let base = '';
    async function close() { if (child.exitCode === null) {
        child.kill('SIGTERM');
        await Promise.race([new Promise<void>(r => child.once('exit', () => r())), new Promise<void>(r => setTimeout(() => { child.kill('SIGKILL'); r(); }, 2000))]);
    } await rm(root, { recursive: true, force: true }); }
    try {
        const port = await new Promise<number>((ok, no) => { let out = ''; const timer = setTimeout(() => no(Error('HTTP fixture startup timeout: ' + errors)), 10000); child.once('error', e => { clearTimeout(timer); no(e); }); child.once('exit', () => { clearTimeout(timer); no(Error('HTTP fixture exited: ' + errors)); }); child.stdout.on('data', b => { out += String(b); if (out.includes('\n')) {
            clearTimeout(timer);
            ok(JSON.parse(out.split('\n')[0]).port);
        } }); });
        base = `http://127.0.0.1:${port}`;
        let ready = false;
        for (let n = 0; n < 100; n++) {
            try {
                await nativeFetch(base + '/fixture/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
                ready = true;
                break;
            }
            catch {
                await new Promise(r => setTimeout(r, 25));
            }
        }
        if (!ready)
            throw Error('HTTP fixture did not become ready: ' + errors);
        async function login(name: string) {
            const r = await nativeFetch(base + '/fixture/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name, secret }) });
            if (!r.ok)
                throw Error(await r.text());
            const session = await r.json();
            const cookie = r.headers.get('set-cookie')!.split(';')[0];
            const transport: typeof fetch = (input, init) => nativeFetch(base + String(input), { ...init, headers: { ...Object.fromEntries(new Headers(init?.headers)), cookie, origin: base } });
            const options = { apiBase: '/api/v1/manufacturing', csrfToken: session.csrf, readOnly: false };
            // The API resolves global fetch at request time; caller installs this transport.
            const api = createWorkflowApi(options);
            return { api, transport, identity: session.identity, options };
        }
        return { login, close, base, root };
    }
    catch (e) {
        await close();
        throw e;
    }
}
export const projectInput = (quantity = '2'): ProjectCreate => ({ operation_id: randomUUID(), name: 'HTTP Camera', line_id: 'Line 1', product: 'Camera', customer_id: 'Customer 1', mode: 'internal', unit: { code: 'piece', scale: 0 }, quantity, contract: { customer_approval_required: false, customer_release_required: false, acceptance_required: true, customer_revision: 'C1', internal_revision: 'M1', material_ownership_rules: 'owned' } });
