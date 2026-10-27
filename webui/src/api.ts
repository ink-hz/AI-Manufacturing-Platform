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
  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    if (revoked) throw new ApiError(403);
    const response = await fetch(base + path, {
      method,
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
    if (response.status === 401 || response.status === 403) {
      if (!revoked) {
        revoked = true;
        onAuthError?.();
      }
      throw new ApiError(response.status);
    }
    if (revoked) throw new ApiError(403);
    if (!response.ok) throw new ApiError(response.status);
    return response.json() as Promise<T>;
  }
  const scope = (line: string, stage?: string) =>
    `/lines/${encodeURIComponent(line)}${stage ? `/stages/${encodeURIComponent(stage)}` : ""}`;
  return {
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
