import type {
  Analysis,
  AnalysisView,
  Investigation,
  InvestigationPatch,
  Overview,
  ResolvedInvestigation,
  Scope,
  TimeFilters,
} from "./types";
type Request = <T>(
  path: string,
  method?: string,
  body?: unknown,
  signal?: AbortSignal,
) => Promise<T>;
export function productionApi(
  request: Request,
  project: (id: string) => string,
  query: (filters: object) => string,
) {
  const drafts = (id: string) => project(id) + "/investigations";
  const handoff = (id: string) =>
    "/production-tools/handoffs/" + encodeURIComponent(id);
  return {
    productionOverview: (
      filters: TimeFilters & { before_id?: string },
      signal?: AbortSignal,
    ) =>
      request<Overview>(
        "/production-tools/overview?" + query(filters),
        "GET",
        undefined,
        signal,
      ),
    productionAnalysis: (
      id: string,
      filters: Scope & { view: AnalysisView },
      signal?: AbortSignal,
    ) =>
      request<Analysis>(
        project(id) + "/analysis?" + query(filters),
        "GET",
        undefined,
        signal,
      ),
    productionAvailability: (id: string, signal?: AbortSignal) =>
      request<{ latest_at: string | null; captured_at: string }>(
        project(id) + "/availability",
        "GET",
        undefined,
        signal,
      ),
    investigations: (id: string, signal?: AbortSignal) =>
      request<{ items: Investigation[]; has_more: boolean }>(
        drafts(id),
        "GET",
        undefined,
        signal,
      ),
    investigation: (id: string, draft: string, signal?: AbortSignal) =>
      request<Investigation>(
        drafts(id) + "/" + encodeURIComponent(draft),
        "GET",
        undefined,
        signal,
      ),
    createInvestigation: (
      id: string,
      body: InvestigationPatch,
      signal?: AbortSignal,
    ) => request<Investigation>(drafts(id), "POST", body, signal),
    updateInvestigation: (
      id: string,
      draft: string,
      body: InvestigationPatch & { expected_version: number },
      signal?: AbortSignal,
    ) =>
      request<Investigation>(
        drafts(id) + "/" + encodeURIComponent(draft),
        "PUT",
        body,
        signal,
      ),
    resolveInvestigation: (id: string, draft: string, signal?: AbortSignal) =>
      request<ResolvedInvestigation>(
        drafts(id) + "/" + encodeURIComponent(draft) + "/resolve",
        "GET",
        undefined,
        signal,
      ),
    createProductionHandoff: (
      id: string,
      draft: string,
      version: number,
      signal?: AbortSignal,
    ) =>
      request<Investigation>(
        drafts(id) + "/" + encodeURIComponent(draft) + "/handoffs",
        "POST",
        { expected_version: version },
        signal,
      ),
    productionHandoff: (id: string, signal?: AbortSignal) =>
      request<Investigation>(handoff(id), "GET", undefined, signal),
    resolveProductionHandoff: (id: string, signal?: AbortSignal) =>
      request<ResolvedInvestigation>(
        handoff(id) + "/resolve",
        "GET",
        undefined,
        signal,
      ),
    forkProductionHandoff: (id: string, signal?: AbortSignal) =>
      request<Investigation>(handoff(id) + "/fork", "POST", {}, signal),
  };
}
