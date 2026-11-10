import type { ProductionStatus, SourceProjectPage, ProductionPage, ProductionStatistics, ObservationFilters, CatalogKind, CatalogFilters, EvidenceFilters } from './productionTools/types';
import type {SystemDescriptor,SystemId,SourceKey,FactPage,FactDetail,FactLinkPage,IntentPage} from './integrations/types';
import type {
  PublicAssetPage,
  AssistanceResult,
  AssistanceKind,
} from "./oemTypes";
import type { MountOptions } from "../types";
import type { Handbook } from "../projects/types";
import type {
  WorkflowBootstrap,
  ProjectCreate,
  ProjectDetail,
  Grant,
  GrantChange,
  GrantResult,
  WorkflowCommand,
  CommandResult,
  ObjectKind,
  ObjectPage,
  ActorTaskPage,
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
  const controllers = new Map<AbortController, () => void>();
  const assert = () => {
    if (retired) throw new DOMException("Workflow retired", "AbortError");
  };
  const dispose = () => {
    retired = true;
    controllers.forEach((cleanup, c) => {
      c.abort();
      cleanup();
    });
    controllers.clear();
  };
  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    assert();
    const c = new AbortController();
    const abort = () => c.abort();
    const cleanup = () => signal?.removeEventListener("abort", abort);
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    controllers.set(c, cleanup);
    const assertCurrent = () => {
      assert();
      if (c.signal.aborted)
        throw new DOMException("Read cancelled", "AbortError");
    };
    try {
      assertCurrent();
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
      assertCurrent();
      if (r.status === 401 || r.status === 403) {
        dispose();
        onAuthError?.();
        throw new WorkflowError(r.status);
      }
      const v = await r.json();
      assertCurrent();
      if (!r.ok)
        throw new WorkflowError(
          r.status,
          v.code,
          v.blocking_reasons || [],
          v.fields || {},
        );
      return v as T;
    } finally {
      if (controllers.delete(c)) cleanup();
    }
  }
  const p = (id: string) => "/projects/" + encodeURIComponent(id);
  const pageQuery = (limit: number, offset: number, projectId?: string) =>
    `?limit=${limit}&offset=${offset}` +
    (projectId === undefined
      ? ""
      : "&project_id=" + encodeURIComponent(projectId));
  const productionPath = (id: string) => {
    if (typeof id !== 'string' || !/^[1-9][0-9]{0,19}$/.test(id)) throw new Error("Invalid source project ID");
    return "/production-tools/projects/" + encodeURIComponent(id);
  };
  const productionQuery = (filters: object) => {
    for (const [key, value] of Object.entries(filters)) {
      if ((key === 'parent_id' || key === 'before_id') && value !== undefined
        && (typeof value !== 'string' || !/^[1-9][0-9]{0,19}$/.test(value))) {
        throw new Error("Invalid source filter ID");
      }
    }
    return new URLSearchParams(
      Object.entries(filters).filter(([, value]) => value !== undefined)
        .map(([key, value]) => [key, String(value)]),
    ).toString();
  };
  return {
    productionProjects: (filters: {before_id?: string} = {}, signal?: AbortSignal) =>
      request<SourceProjectPage>("/production-tools/projects" + (filters.before_id === undefined ? "" : "?" + productionQuery(filters)), "GET", undefined, signal),
    productionStatus: (id?: string, signal?: AbortSignal) =>
      request<ProductionStatus>((id === undefined ? "/production-tools" : productionPath(id)) + "/status", "GET", undefined, signal),
    productionObservations: (id: string, filters: ObservationFilters, signal?: AbortSignal) =>
      request<ProductionPage>(productionPath(id) + "/observations?" + productionQuery(filters), "GET", undefined, signal),
    productionCatalog: (id: string, kind: CatalogKind, filters: CatalogFilters, signal?: AbortSignal) =>
      request<ProductionPage>(productionPath(id) + "/catalog/" + encodeURIComponent(kind) + "?" + productionQuery(filters), "GET", undefined, signal),
    productionEvidence: (id: string, filters: EvidenceFilters, signal?: AbortSignal) =>
      request<ProductionPage>(productionPath(id) + "/evidence?" + productionQuery(filters), "GET", undefined, signal),
    productionStatistics: (id: string, filters: ObservationFilters, signal?: AbortSignal) =>
      request<ProductionPage<ProductionStatistics>>(productionPath(id) + "/statistics?" + productionQuery(filters), "GET", undefined, signal),
    productionSnapshot: (id: string, snapshotId: string, offset = 0, limit = 50, signal?: AbortSignal) =>
      request<ProductionPage>(productionPath(id) + "/snapshots/" + encodeURIComponent(snapshotId) + "?" + productionQuery({offset, limit}), "GET", undefined, signal),
    productionEvidenceUrl: (id: string, sourceLogId: string) => {
      assert();
      if (typeof sourceLogId !== 'string' || !/^[1-9][0-9]{0,19}$/.test(sourceLogId)) throw new Error("Invalid evidence ID");
      return base + "/workflow" + productionPath(id) + "/evidence/" + encodeURIComponent(sourceLogId) + "/content";
    },
    systems: (id:string, signal?:AbortSignal) => request<SystemDescriptor[]>(p(id)+"/systems", "GET", undefined, signal),
    systemFacts: (id:string, system:SystemId, filters:{object_type:string;cursor?:number;limit?:number}, signal?:AbortSignal) => request<FactPage>(p(id)+"/systems/"+encodeURIComponent(system)+"/facts?"+new URLSearchParams({object_type:filters.object_type,cursor:String(filters.cursor||0),limit:String(filters.limit||50)}), "GET", undefined, signal),
    systemFact: (id:string, key:SourceKey, signal?:AbortSignal) => request<FactDetail>(p(id)+"/systems/"+encodeURIComponent(key.system)+"/facts/"+encodeURIComponent(key.object_type)+"/"+encodeURIComponent(key.external_id)+"?version="+key.version, "GET", undefined, signal),
    integrationLinks: (id:string, kind:ObjectKind, object:string, cursor=0, signal?:AbortSignal) => request<FactLinkPage>(p(id)+"/integration-links?"+new URLSearchParams({target_kind:kind,target_id:object,cursor:String(cursor),limit:'50'}), "GET", undefined, signal),
    integrationIntents: (id:string, limit=50, offset=0, signal?:AbortSignal) => request<IntentPage>(p(id)+`/integration-intents?limit=${limit}&offset=${offset}`, "GET", undefined, signal),
    publicAssets: (limit = 50, offset = 0, signal?: AbortSignal) =>
      request<PublicAssetPage>(
        "/reusable-assets" + pageQuery(limit, offset),
        "GET",
        undefined,
        signal,
      ),
    assistance: (id: string, kind: AssistanceKind, signal?: AbortSignal) =>
      request<AssistanceResult>(
        p(id) + "/assistance?kind=" + encodeURIComponent(kind),
        "GET",
        undefined,
        signal,
      ),
    ledger: (
      kind: ObjectKind,
      limit = 50,
      offset = 0,
      projectId?: string,
      signal?: AbortSignal,
    ) =>
      request<ObjectPage>(
        "/objects/" + kind + pageQuery(limit, offset, projectId),
        "GET",
        undefined,
        signal,
      ),
    tasks: (limit = 50, offset = 0, projectId?: string, signal?: AbortSignal) =>
      request<ActorTaskPage>(
        "/tasks" + pageQuery(limit, offset, projectId),
        "GET",
        undefined,
        signal,
      ),
    bootstrap: () => request<WorkflowBootstrap>("/access"),
    projects: (signal?: AbortSignal) =>
      request<{ items: ProjectDetail[] }>(
        "/projects",
        "GET",
        undefined,
        signal,
      ),
    project: (id: string, signal?: AbortSignal) =>
      request<ProjectDetail>(p(id), "GET", undefined, signal),
    createProject: (v: ProjectCreate) =>
      request<ProjectDetail>("/projects", "POST", v),
    members: (id: string, limit?: number, offset = 0) =>
      request<{ items: Grant[] }>(
        p(id) +
          "/members" +
          (limit === undefined ? "" : `?limit=${limit}&offset=${offset}`),
      ),
    member: (id: string, user: string) =>
      request<{ items: Grant[] }>(
        p(id) + "/members?user_id=" + encodeURIComponent(user),
      ),
    grant: (id: string, user: string, v: GrantChange) =>
      request<GrantResult>(
        p(id) + "/members/" + encodeURIComponent(user),
        "PUT",
        v,
      ),
    objects: (
      id: string,
      kind: ObjectKind,
      limit = 50,
      offset = 0,
      signal?: AbortSignal,
    ) =>
      request<ObjectPage>(
        p(id) + "/objects/" + kind + `?limit=${limit}&offset=${offset}`,
        "GET",
        undefined,
        signal,
      ),
    object: (
      id: string,
      kind: ObjectKind,
      object: string,
      signal?: AbortSignal,
    ) =>
      request<ObjectDetail>(
        p(id) + "/objects/" + kind + "/" + encodeURIComponent(object),
        "GET",
        undefined,
        signal,
      ),
    command: (id: string, v: WorkflowCommand) =>
      request<CommandResult>(p(id) + "/commands", "POST", v),
    dashboard: (signal?: AbortSignal) =>
      request<Dashboard>("/dashboard", "GET", undefined, signal),
    exchanges: (id: string, limit = 50, offset = 0) =>
      request<ObjectPage>(p(id) + `/exchanges?limit=${limit}&offset=${offset}`),
    trace: (
      id: string,
      query:
        | { sn: string; material_lot_id?: never }
        | { material_lot_id: string; sn?: never },
      limit = 500,
    ) => {
      const params = new URLSearchParams();
      if (query.sn !== undefined) params.set("sn", query.sn);
      else params.set("material_lot_id", query.material_lot_id);
      params.set("limit", String(limit));
      return request<TraceResult>(p(id) + "/trace?" + params);
    },
    handbook: () => request<Handbook>("/handbook"),
    dispose,
  };
}
export type WorkflowApi = ReturnType<typeof createWorkflowApi>;
