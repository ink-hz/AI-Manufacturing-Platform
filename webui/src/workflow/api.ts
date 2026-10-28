import type { MountOptions } from "../types";
import type { Handbook } from "../projects/types";
import type {
  WorkflowBootstrap,
  ProjectCreate,
  ProjectDetail,
  Grant,
  GrantChange,
  WorkflowCommand,
  CommandResult,
  ObjectKind,
  ObjectPage,
  ObjectDetail,
  Dashboard,
  TraceResult,
} from "./types";
export class WorkflowError extends Error {
  constructor(
    public status: number,
    public code = "",
    public reasons: string[] = [],
    public fields: Record<string, unknown> = {},
  ) {
    super(
      status === 409
        ? "资料冲突或业务条件未满足，草稿已保留。请核对后重试或重新读取。"
        : status === 403 || status === 401
          ? "无权访问，请重新登录。"
          : status === 422
            ? "请检查必填资料、凭据和业务状态。"
            : "读取或保存失败，草稿已保留，可重试。",
    );
  }
}
export function createWorkflowApi(
  options: MountOptions,
  onAuthError = options.onAuthError,
) {
  const base = options.apiBase.replace(/\/+$/, "");
  if (
    !base.startsWith("/") ||
    base.startsWith("//") ||
    new URL(base, location.origin).origin !== location.origin ||
    base.endsWith("/workflow")
  )
    throw new Error("Expected same-origin manufacturing API root");
  let retired = false;
  const controllers = new Set<AbortController>();
  const assert = () => {
    if (retired) throw new DOMException("Workflow retired", "AbortError");
  };
  const dispose = () => {
    retired = true;
    controllers.forEach((c) => c.abort());
    controllers.clear();
  };
  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    assert();
    const c = new AbortController();
    controllers.add(c);
    try {
      const r = await fetch(base + "/workflow" + path, {
        method,
        signal: c.signal,
        credentials: "same-origin",
        cache: "no-store",
        headers:
          body === undefined
            ? {}
            : {
                "Content-Type": "application/json",
                "X-CSRF-Token": options.csrfToken,
              },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      assert();
      if (r.status === 401 || r.status === 403) {
        dispose();
        onAuthError?.();
        throw new WorkflowError(r.status);
      }
      const v = await r.json();
      assert();
      if (!r.ok)
        throw new WorkflowError(
          r.status,
          v.code,
          v.blocking_reasons || [],
          v.fields || {},
        );
      return v as T;
    } finally {
      controllers.delete(c);
    }
  }
  const p = (id: string) => "/projects/" + encodeURIComponent(id);
  return {
    bootstrap: () => request<WorkflowBootstrap>("/access"),
    projects: () => request<{ items: ProjectDetail[] }>("/projects"),
    project: (id: string) => request<ProjectDetail>(p(id)),
    createProject: (v: ProjectCreate) =>
      request<ProjectDetail>("/projects", "POST", v),
    members: (id: string, limit?:number, offset=0) => request<{ items: Grant[] }>(p(id) + "/members" + (limit===undefined?"":`?limit=${limit}&offset=${offset}`)),
    member: (id: string, user: string) => request<{ items: Grant[] }>(p(id) + "/members?user_id=" + encodeURIComponent(user)),
    grant: (id: string, user: string, v: GrantChange) =>
      request<CommandResult>(
        p(id) + "/members/" + encodeURIComponent(user),
        "PUT",
        v,
      ),
    objects: (id: string, kind: ObjectKind, limit = 50, offset = 0) =>
      request<ObjectPage>(
        p(id) + "/objects/" + kind + `?limit=${limit}&offset=${offset}`,
      ),
    object: (id: string, kind: ObjectKind, object: string) =>
      request<ObjectDetail>(
        p(id) + "/objects/" + kind + "/" + encodeURIComponent(object),
      ),
    command: (id: string, v: WorkflowCommand) =>
      request<CommandResult>(p(id) + "/commands", "POST", v),
    dashboard: () => request<Dashboard>("/dashboard"),
    exchanges: (id: string, limit=50, offset=0) => request<ObjectPage>(p(id) + `/exchanges?limit=${limit}&offset=${offset}`),
    trace: (id: string, query: {sn:string;material_lot_id?:never}|{material_lot_id:string;sn?:never}, limit=500) => {
      const params=new URLSearchParams();
      if(query.sn!==undefined)params.set("sn",query.sn);else params.set("material_lot_id",query.material_lot_id);
      params.set("limit",String(limit));
      return request<TraceResult>(p(id)+"/trace?"+params);
    },
    handbook: () => request<Handbook>("/handbook"),
    dispose,
  };
}
export type WorkflowApi = ReturnType<typeof createWorkflowApi>;
