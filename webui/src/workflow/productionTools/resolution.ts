import { useEffect, useRef, useState } from "react";
import type { Api } from "./boards";
import type {
  Investigation,
  ResolvedInvestigation,
  ViewedEvent,
} from "./types";
import { errorText } from "./context";
const emptyRaw = () => ({
  primary: null as ViewedEvent | null,
  comparison: null as ViewedEvent | null,
});
function identity(user: string, d: Investigation, isHandoff: boolean) {
  return JSON.stringify([
    user,
    d.source_namespace,
    d.source_project_id,
    isHandoff ? "handoff" : "draft",
    d.id,
    d.version,
    d.primary,
    d.comparison,
    d.logs,
  ]);
}
/** Only the current record/revision and the newest request may publish verified evidence. */
export function useInvestigationResolution(
  api: Api,
  user: string,
  record: Investigation | null,
  isHandoff: boolean,
  onError: (text: string) => void,
) {
  const owner = record ? identity(user, record, isHandoff) : null;
  const latest = useRef(owner);
  latest.current = owner;
  const request = useRef<{
    generation: number;
    controller: AbortController | null;
  }>({ generation: 0, controller: null });
  const [value, setValue] = useState<{
    owner: string | null;
    resolved: ResolvedInvestigation | null;
    raw: ReturnType<typeof emptyRaw>;
  }>({ owner: null, resolved: null, raw: emptyRaw() });
  function invalidate() {
    request.current.generation++;
    request.current.controller?.abort();
    request.current.controller = null;
    setValue({ owner: null, resolved: null, raw: emptyRaw() });
  }
  useEffect(() => {
    if (value.owner !== owner) invalidate();
  }, [owner]);
  useEffect(
    () => () => {
      request.current.generation++;
      request.current.controller?.abort();
    },
    [api, user],
  );
  async function resolve(d: Investigation, handoff = false) {
    invalidate();
    const key = identity(user, d, handoff),
      generation = request.current.generation,
      c = new AbortController();
    request.current.controller = c;
    try {
      const result = handoff
        ? await api.resolveProductionHandoff(d.id, c.signal)
        : await api.resolveInvestigation(d.source_project_id, d.id, c.signal);
      if (
        c.signal.aborted ||
        generation !== request.current.generation ||
        latest.current !== key
      )
        return;
      const binding = result.binding;
      if (
        !binding ||
        binding.kind !== (handoff ? "handoff" : "draft") ||
        binding.id !== d.id ||
        binding.version !== d.version ||
        binding.primary_selection_id !== (d.primary?.selection_id ?? null) ||
        binding.comparison_selection_id !== (d.comparison?.selection_id ?? null)
      ) {
        onError(
          "复查结果属于其他修订或事件，当前参数未核对；请重新读取服务端调查。",
        );
        return;
      }
      const event = (which: "primary" | "comparison"): ViewedEvent | null => {
        const part = result[which];
        return d[which] &&
          part?.state === "verified" &&
          part.candidates.length === 1
          ? {
              ...part.candidates[0],
              projectId: d.source_project_id,
              kind: d[which]!.source_kind,
              captured_at: result.captured_at,
            }
          : null;
      };
      setValue({
        owner: key,
        resolved: result,
        raw: { primary: event("primary"), comparison: event("comparison") },
      });
    } catch (e) {
      if (
        !c.signal.aborted &&
        generation === request.current.generation &&
        latest.current === key
      )
        onError(errorText(e));
    }
  }
  return {
    resolved: value.owner === owner ? value.resolved : null,
    raw: value.owner === owner ? value.raw : emptyRaw(),
    invalidate,
    resolve,
  };
}
