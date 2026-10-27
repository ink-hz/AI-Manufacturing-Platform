import type {
  Dashboard,
  ProjectSummary,
  ProjectCreate,
  ProjectWrite,
  ProjectDetailData,
  StageWrite,
  ProjectStage,
  FlatTask,
  ProjectTaskCreate,
  ProjectTaskWrite,
  ProjectTask,
  Handbook,
  DocumentName,
} from "./projects/types";
import type {
  Catalog,
  LineOverview,
  MountOptions,
  RecordWrite,
  StageRecord,
  StageResponse,
  Task,
  TaskCreate,
  TaskWrite,
} from "./types";
export class ApiError extends Error {
  constructor(public status: number) {
    super(
      status === 409
        ? "内容已更新，请核对后再保存"
        : status === 401 || status === 403
          ? "无权访问"
          : "请求失败，请重试",
    );
  }
}
export function createApi(
  options: MountOptions,
  onAuthError = options.onAuthError,
) {
  const base = options.apiBase.replace(/\/+$/, "");
  if (
    !base.startsWith("/") ||
    base.startsWith("//") ||
    new URL(base, location.origin).origin !== location.origin
  )
    throw new Error("apiBase must be a same-origin path");
  let revoked = false;
  let disposed = false;
  const controllers = new Set<AbortController>();
  function assertActive() {
    if (disposed)
      throw new DOMException("Manufacturing instance retired", "AbortError");
    if (revoked) throw new ApiError(403);
  }
  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    assertActive();
    const controller = new AbortController();
    controllers.add(controller);
    try {
      const response = await fetch(base + path, {
        method,
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
        headers:
          body === undefined
            ? {}
            : {
                "Content-Type": "application/json",
                "X-CSRF-Token": options.csrfToken,
              },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      // Some transports may still resolve after abort. Lifetime checks, rather
      // than the abort signal alone, prevent retired instances notifying hosts.
      assertActive();
      if (response.status === 401 || response.status === 403) {
        revoked = true;
        onAuthError?.();
        throw new ApiError(response.status);
      }
      if (!response.ok) throw new ApiError(response.status);
      const result = (await response.json()) as T;
      assertActive();
      return result;
    } finally {
      controllers.delete(controller);
    }
  }

  const scope = (line: string, stage?: string) =>
    `/lines/${encodeURIComponent(line)}${stage ? `/stages/${encodeURIComponent(stage)}` : ""}`;
  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const controller of controllers) controller.abort();
      controllers.clear();
    },
    dashboard: () => request<Dashboard>("/dashboard"),
    projects: () => request<{ items: ProjectSummary[] }>("/projects"),
    project: (id: string) =>
      request<ProjectDetailData>(`/projects/${encodeURIComponent(id)}`),
    createProject: (body: ProjectCreate) =>
      request<ProjectDetailData>("/projects", "POST", body),
    updateProject: (id: string, body: ProjectWrite) =>
      request<ProjectDetailData>(
        `/projects/${encodeURIComponent(id)}`,
        "PATCH",
        body,
      ),
    saveProjectStage: (id: string, stage: string, body: StageWrite) =>
      request<ProjectStage>(
        `/projects/${encodeURIComponent(id)}/stages/${encodeURIComponent(stage)}`,
        "PUT",
        body,
      ),
    projectTasks: () => request<{ items: FlatTask[] }>("/project-tasks"),
    createProjectTask: (id: string, body: ProjectTaskCreate) =>
      request<ProjectTask>(
        `/projects/${encodeURIComponent(id)}/tasks`,
        "POST",
        body,
      ),
    updateProjectTask: (id: string, task: string, body: ProjectTaskWrite) =>
      request<ProjectTask>(
        `/projects/${encodeURIComponent(id)}/tasks/${encodeURIComponent(task)}`,
        "PATCH",
        body,
      ),
    handbook: (document: DocumentName = "handbook", release?: string) =>
      request<Handbook>(
        `/handbook?document=${document}${release === undefined ? "" : `&release=${encodeURIComponent(release)}`}`,
      ),
    catalog: () => request<Catalog>("/catalog"),
    line: (line: string) => request<LineOverview>(scope(line)),
    stage: (line: string, stage: string) =>
      request<StageResponse>(scope(line, stage)),
    saveRecord: (line: string, stage: string, body: RecordWrite) =>
      request<StageRecord>(scope(line, stage), "PUT", body),
    createTask: (line: string, stage: string, body: TaskCreate) =>
      request<Task>(scope(line, stage) + "/tasks", "POST", body),
    updateTask: (line: string, stage: string, id: string, body: TaskWrite) =>
      request<Task>(
        scope(line, stage) + "/tasks/" + encodeURIComponent(id),
        "PATCH",
        body,
      ),
  };
}
export type Api = ReturnType<typeof createApi>;
