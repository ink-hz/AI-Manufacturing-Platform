import type { SapStatus, SapObservation, SapOrder, SapMrp } from "./sapTypes";
type Request = <T>(
  path: string,
  method?: string,
  body?: unknown,
  signal?: AbortSignal,
) => Promise<T>;
export function sapApi(request: Request) {
  const path = "/material-control/sap";
  return {
    sapMaterialStatus: (signal?: AbortSignal) =>
      request<SapStatus>(path + "/status", "GET", undefined, signal),
    sapProductionOrder: (
      number: string,
      plant: string,
      refresh: boolean,
      signal?: AbortSignal,
    ) =>
      request<SapObservation<SapOrder>>(
        path + "/production-order?" + new URLSearchParams({ number, plant }),
        refresh ? "POST" : "GET",
        undefined,
        signal,
      ),
    sapStockRequirements: (
      material: string,
      plant: string,
      refresh: boolean,
      signal?: AbortSignal,
    ) =>
      request<SapObservation<SapMrp>>(
        path +
          "/stock-requirements?" +
          new URLSearchParams({ material, plant }),
        refresh ? "POST" : "GET",
        undefined,
        signal,
      ),
  };
}
