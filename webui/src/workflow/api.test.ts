import { it, expect, vi, afterEach } from "vitest";
import { createWorkflowApi } from "./api";
afterEach(() => vi.unstubAllGlobals());
it("uses one workflow prefix with CSRF and retires late responses", async () => {
  let resolve!: (r: Response) => void;
  const fetcher = vi.fn(
    (_url: string, _init?: RequestInit) =>
      new Promise<Response>((r) => (resolve = r)),
  );
  vi.stubGlobal("fetch", fetcher);
  const auth = vi.fn();
  const api = createWorkflowApi(
    {
      apiBase: "/preview/api/v1/manufacturing",
      csrfToken: "csrf",
      readOnly: false,
    },
    auth,
  );
  const pending = api.projects();
  api.dispose();
  resolve(new Response("{}", { status: 403 }));
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(auth).not.toHaveBeenCalled();
  expect(fetcher.mock.calls[0][0]).toBe(
    "/preview/api/v1/manufacturing/workflow/projects",
  );
});
it("sends exact command data and CSRF without actor fields", async () => {
  const body = {
    action: "demand.review" as const,
    operation_id: "00000000-0000-4000-8000-000000000001",
    expected_version: 2,
    demand_id: "00000000-0000-4000-8000-000000000002",
    dimension: "technical" as const,
    decision: "approved" as const,
    evidence: "技术评审单",
  };
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          operation_id: body.operation_id,
          project_id: "p",
          project_version: 3,
          object_type: "demand",
          object_id: body.demand_id,
          exchange_id: null,
          replayed: false,
        }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const api = createWorkflowApi({
    apiBase: "/api/v1/manufacturing",
    csrfToken: "csrf",
    readOnly: false,
  });
  await api.command("p", body);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/manufacturing/workflow/projects/p/commands",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf" },
      cache: "no-store",
      credentials: "same-origin",
    }),
  );
  api.dispose();
});
it("retains structured conflict fields and blocking reasons", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            code: "VERSION_CONFLICT",
            message: "Project version changed",
            fields: { current_version: 9, source_version: 2 },
            blocking_reasons: ["change disposition pending"],
          }),
          { status: 409 },
        ),
    ),
  );
  const api = createWorkflowApi({
    apiBase: "/api/v1/manufacturing",
    csrfToken: "csrf",
    readOnly: false,
  });
  await expect(api.project("p")).rejects.toMatchObject({
    status: 409,
    code: "VERSION_CONFLICT",
    fields: { current_version: 9, source_version: 2 },
    reasons: ["change disposition pending"],
  });
  api.dispose();
});

it("requests typed global ledger and task pages with bounded encoded filters", async () => {
  const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({items:[],total:0,limit:50,offset:0,truncated:false})));
  vi.stubGlobal("fetch", fetcher);
  const api = createWorkflowApi({apiBase:"/preview/api/v1/manufacturing/",csrfToken:"csrf",readOnly:false});
  await api.ledger("order_line");
  const tasks = await api.tasks(7, 14, "project /?#");
  await api.ledger("shipment", 3, 2, "project /?#");
  expect(tasks.truncated).toBe(false);
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([
    "/preview/api/v1/manufacturing/workflow/objects/order_line?limit=50&offset=0",
    "/preview/api/v1/manufacturing/workflow/tasks?limit=7&offset=14&project_id=project%20%2F%3F%23",
    "/preview/api/v1/manufacturing/workflow/objects/shipment?limit=3&offset=2&project_id=project%20%2F%3F%23",
  ]);
  expect(fetcher).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({method:"GET", credentials:"same-origin",cache:"no-store",headers:{}}));
  api.dispose();
});

it.each(["ledger", "tasks"] as const)("retires %s requests on auth failures and disposal", async method => {
  let resolve!: (r:Response)=>void;
  const fetcher = vi.fn((_url:string,_init?:RequestInit)=>new Promise<Response>(r=>resolve=r));
  vi.stubGlobal("fetch",fetcher);
  const auth=vi.fn();
  const api=createWorkflowApi({apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false},auth);
  const call=()=>method==="ledger"?api.ledger("demand"):api.tasks();
  const pending=call();
  resolve(new Response("{}",{status:401}));
  await expect(pending).rejects.toMatchObject({status:401});
  expect(auth).toHaveBeenCalledOnce();
  await expect(call()).rejects.toMatchObject({name:"AbortError"});
  const replacement=createWorkflowApi({apiBase:"/api/v1/manufacturing",csrfToken:"csrf",readOnly:false},auth);
  const late=method==="ledger"?replacement.ledger("demand"):replacement.tasks();
  replacement.dispose();
  expect(fetcher.mock.calls[1][1]?.signal?.aborted).toBe(true);
  resolve(new Response("{}"));
  await expect(late).rejects.toMatchObject({name:"AbortError"});
});

it.each([401,403,200])('cancels caller-owned reads before late %s transport outcomes and cleans listeners', async status => {
  let finish!:(r:Response)=>void;
  const fetcher=vi.fn((_url:string,_init?:RequestInit)=>new Promise<Response>(r=>finish=r));
  vi.stubGlobal('fetch',fetcher);
  const auth=vi.fn(), api=createWorkflowApi({apiBase:'/api/v1/manufacturing',csrfToken:'csrf',readOnly:false},auth);
  const owner=new AbortController(), remove=vi.spyOn(owner.signal,'removeEventListener');
  const pending=api.ledger('demand',50,0,undefined,owner.signal);
  owner.abort();
  const aborted=fetcher.mock.calls[0][1]?.signal?.aborted;
  finish(new Response('{}',{status}));
  await expect(pending).rejects.toMatchObject({name:'AbortError'});
  expect(aborted).toBe(true);expect(auth).not.toHaveBeenCalled();
  expect(remove).toHaveBeenCalledWith('abort',expect.any(Function));
  vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}')));
  await expect(api.project('current')).resolves.toEqual({});api.dispose();
});
it('checks caller cancellation after body parsing and removes listeners on completion/disposal',async()=>{
  const owner=new AbortController(), remove=vi.spyOn(owner.signal,'removeEventListener');
  let finish!:(v:unknown)=>void;
  vi.stubGlobal('fetch',vi.fn(async()=>({status:200,ok:true,json:()=>new Promise(r=>finish=r)})));
  const api=createWorkflowApi({apiBase:'/api/v1/manufacturing',csrfToken:'csrf',readOnly:false});
  const pending=api.project('p',owner.signal);await Promise.resolve();owner.abort();finish({id:'old'});
  await expect(pending).rejects.toMatchObject({name:'AbortError'});expect(remove).toHaveBeenCalledOnce();
  const next=new AbortController(), cleanup=vi.spyOn(next.signal,'removeEventListener');
  vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}')));
  await api.tasks(50,0,undefined,next.signal);expect(cleanup).toHaveBeenCalledOnce();
  const last=new AbortController(), disposeCleanup=vi.spyOn(last.signal,'removeEventListener');
  let settle!:(v:Response)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>settle=r)));
  const disposed=api.projects(last.signal);api.dispose();expect(disposeCleanup).toHaveBeenCalledOnce();
  settle(new Response('{}',{status:401}));await expect(disposed).rejects.toMatchObject({name:'AbortError'});
});
it('does not send a pre-cancelled read and still denies a current authenticated request',async()=>{
 const fetcher=vi.fn(async()=>new Response('{}',{status:401})),auth=vi.fn();vi.stubGlobal('fetch',fetcher);
 const api=createWorkflowApi({apiBase:'/api/v1/manufacturing',csrfToken:'csrf',readOnly:false},auth),owner=new AbortController();owner.abort();
 await expect(api.dashboard(owner.signal)).rejects.toMatchObject({name:'AbortError'});expect(fetcher).not.toHaveBeenCalled();
 await expect(api.project('current',new AbortController().signal)).rejects.toMatchObject({status:401});expect(auth).toHaveBeenCalledOnce();
});
