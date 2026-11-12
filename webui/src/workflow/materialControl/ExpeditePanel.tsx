import { useMaterialCommand } from "./useMaterialCommand";
import { useEffect, useRef, useState, type RefObject } from "react";
import { WorkflowError } from "../api";
import { ExpediteHistory } from "./ExpediteHistory";
import { ExpediteFulfillment } from "./ExpediteFulfillment";
import type { ExpediteValue, FulfillmentCheck } from "./fulfillmentTypes";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import type { MaterialProject, MaterialRequirement } from "./types";
import type { CommandFields } from "../types";

type CaseRecord = MaterialProject["expedites"][number] & Pick<ExpediteValue, "closure">;
export function ExpeditePanel({ p, page, requirement, active, begin, resetRef, intent }: {
  p: OEMWorkspaceProps; page: MaterialProject; requirement: MaterialRequirement; active: boolean;
  begin(f: () => void): void; resetRef: RefObject<() => void>;
  intent?: { requirementId: string; token: number; expediteId?: string } | null;
}) {
  const command = useMaterialCommand(p.api, p.project.id);
  const [version, setVersion] = useState(p.project.version);
  const [action, setAction] = useState<"open" | "progress" | "close" | null>(null);
  const [id, setId] = useState("");
  const [reason, setReason] = useState(""), [impact, setImpact] = useState("");
  const [outcome, setOutcome] = useState<"fulfilled" | "false_alarm" | "superseded">("fulfilled");
  const [error, setError] = useState(""), [reasons, setReasons] = useState<string[]>([]);
  const [saving, setSaving] = useState(false), [checking, setChecking] = useState(false);
  const [check, setCheck] = useState<FulfillmentCheck | null>(null), [invalidated, setInvalidated] = useState(false);
  const [extra, setExtra] = useState<CaseRecord | null>(null);
  const epoch = useRef(0), alive = useRef(true), seenIntent = useRef<number | null>(null);
  const checkingRequest = useRef<AbortController | null>(null);
  const available = (a: string) => !p.readOnly && p.project.allowed_actions.some(x => x === a);
  const entries = (page.expedites as CaseRecord[]).filter(x => requirement.expedite_ids.includes(x.id));
  if (extra && !entries.some(x => x.id === extra.id)) entries.push(extra);
  const fresh = !!check && !invalidated && check.project_version === version && version === p.project.version;
  const canFulfill = fresh && check!.can_fulfill && !check!.blocking_reasons.length && !checking;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; epoch.current++; checkingRequest.current?.abort(); };
  }, [p.api, p.project.id, requirement.id]);
  function clear() {
    epoch.current++; checkingRequest.current?.abort(); command.clear();
    setAction(null); setId(""); setReason(""); setImpact(""); setOutcome("fulfilled");
    setError(""); setReasons([]); setCheck(null); setChecking(false); setSaving(false); setInvalidated(false);
    setExtra(null);
    p.onDirty("material-expedite", false);
  }
  useEffect(() => { resetRef.current = clear; return () => { resetRef.current = () => {}; }; });

  async function loadCase(caseId: string, token: number, forClose: boolean) {
    const c = new AbortController(); checkingRequest.current?.abort(); checkingRequest.current = c;
    setChecking(true);
    try {
      const detail = await p.api.object(p.project.id, "material_expedite", caseId, c.signal);
      if (!alive.current || c.signal.aborted || token !== epoch.current) return;
      const value = detail.value as unknown as ExpediteValue;
      if (value.kind !== "material_expedite") throw Error("急料记录已变化，请重新读取。");
      const known = entries.some(e => e.id === caseId);
      if (!known && value.requirement_id !== requirement.id && value.fulfillment_check?.current_requirement_id !== requirement.id)
        throw Error("急料与当前需求不匹配，请重新读取。");
      if (!known) setExtra(value);
      if (forClose) {
        setCheck(value.fulfillment_check);
        if (!value.fulfillment_check) setError("暂无满足核对结果，请重新读取。");
        else if (value.fulfillment_check.project_version > p.project.version)
          (p.onMaterialChanged || p.onChanged)({ project_id: p.project.id, project_version: value.fulfillment_check.project_version });
      }
    } catch (e) {
      if (alive.current && !c.signal.aborted && token === epoch.current) {
        if (e instanceof WorkflowError && [401, 403].includes(e.status)) clear();
        setError(e instanceof Error ? e.message : "核对读取失败，请重试。");
      }
    } finally {
      if (alive.current && !c.signal.aborted && token === epoch.current) setChecking(false);
    }
  }
  function openDirect(next: "open" | "progress" | "close" | null, caseId = "") {
    clear(); setVersion(p.project.version); setAction(next); setId(caseId);
    if (caseId && (next === "close" || !entries.some(e => e.id === caseId)))
      void loadCase(caseId, epoch.current, next === "close");
  }
  const start = (next: "open" | "progress" | "close", caseId = "") => begin(() => openDirect(next, caseId));
  function refreshCheck() {
    if (saving || checking) return;
    if (version !== p.project.version || check && check.project_version !== version) { start("close", id); return; }
    setError(""); setReasons([]); setCheck(null); setInvalidated(false);
    void loadCase(id, epoch.current, true);
  }
  useEffect(() => {
    if (!intent || !active || intent.requirementId !== requirement.id || seenIntent.current === intent.token) return;
    seenIntent.current = intent.token;
    if (intent.expediteId) openDirect(available("expedite.progress") ? "progress" : null, intent.expediteId);
    else if (available("expedite.open")) openDirect("open");
  }, [intent?.token, active, requirement.id]);

  async function submit() {
    if (version !== p.project.version || !action || !available("expedite." + action)
        || !reason.trim() || action === "open" && !impact.trim() || saving
        || action === "close" && outcome === "fulfilled" && !canFulfill) return;
    const fields: CommandFields = action === "open"
      ? { action: "expedite.open", requirement_id: requirement.id, reason, impact }
      : action === "progress" ? { action: "expedite.progress", expedite_id: id, note: reason }
      : { action: "expedite.close", expedite_id: id, outcome, reason };
    const token = epoch.current;
    setSaving(true); setError(""); setReasons([]);
    try {
      const result = await command.execute(fields, version, result => {
        if (p.onMaterialChanged) p.onMaterialChanged(result);
        else if (alive.current && token === epoch.current) p.onChanged(result);
      });
      if (!result || !alive.current || token !== epoch.current) return;
      p.onDirty("material-expedite", false); setAction(null); setReason(""); setImpact("");
    } catch (e) {
      if (alive.current && token === epoch.current) {
        if (e instanceof WorkflowError && [401, 403].includes(e.status)) clear();
        setError(String(e));
        if (e instanceof WorkflowError) { setReasons(e.reasons); if (e.status === 409) setInvalidated(true); }
      }
    } finally { if (alive.current && token === epoch.current) setSaving(false); }
  }
  const edit = (f: (v: string) => void, value: string) => { f(value); p.onDirty("material-expedite", true); };
  const reasonLabel = action === "progress" ? "进展说明" : action === "close" ? "结束说明" : "催料原因";
  return <section aria-label="催料办理">
    <h5>催料</h5>
    {!entries.length && <p>暂无催料记录</p>}
    {entries.map(x => <div key={x.id}>
      <p>{x.expedite_number}：{x.reason} {x.state === "open" ? "处理中" : "已结束"}</p>
      {id === x.id && <p>影响：{x.impact}</p>}
      {x.progress?.map((v, index) => <p key={index}>{v.note}</p>)}
      {x.progress_truncated && <ExpediteHistory api={p.api} projectId={p.project.id} id={x.id} total={x.progress_total} />}
      {x.closure && <p>{x.closure.outcome === "fulfilled"
        ? x.closure.fulfillment_proof ? "已按凭据核对满足" : "历史结束记录，未留存数量核对依据"
        : x.closure.outcome === "false_alarm" ? "误报结束" : "已替代结束"}</p>}
      {x.state === "open" && <div className="mf-actions">
        {available("expedite.progress") && <button onClick={() => start("progress", x.id)}>更新催料进展</button>}
        {available("expedite.close") && <button onClick={() => start("close", x.id)}>结束催料</button>}
      </div>}
    </div>)}
    {available("expedite.open") && <button onClick={() => start("open")}>发起催料</button>}
    {active && action && <div>
      {version !== p.project.version && <p>项目已更新，草稿已保留；请重新打开操作。</p>}
      {action === "close" && <>
        {checking && <p role="status">正在核对当前满足情况…</p>}
        {check && <ExpediteFulfillment value={check} fresh={fresh} />}
        {(!check || !fresh) && !checking && <button onClick={refreshCheck}>
          {version !== p.project.version || check && check.project_version !== version ? "重新打开核对" : "重新核对"}
        </button>}
      </>}
      <label>{reasonLabel}<input aria-label={reasonLabel} value={reason} disabled={saving || p.readOnly}
        onChange={e => edit(setReason, e.target.value)} /></label>
      {action === "open" && <label>影响<input aria-label="影响" value={impact} disabled={saving || p.readOnly} onChange={e => edit(setImpact, e.target.value)} /></label>}
      {action === "close" && <label>结果<select aria-label="结果" value={outcome} disabled={saving || p.readOnly}
        onChange={e => edit(v => setOutcome(v as typeof outcome), e.target.value)}>
        <option value="fulfilled">按凭据核对满足</option><option value="false_alarm">误报结束</option><option value="superseded">已替代结束</option>
      </select></label>}
      {error && <p role="alert">{error}</p>}{reasons.map((v, index) => <p role="alert" key={index}>{v}</p>)}
      <button disabled={saving || version !== p.project.version || !available("expedite." + action)
        || !reason.trim() || action === "open" && !impact.trim()
        || action === "close" && outcome === "fulfilled" && !canFulfill} onClick={() => void submit()}>
        {action === "open" ? "提交催料" : action === "progress" ? "保存进展" : "确认结束"}
      </button>
    </div>}
  </section>;
}
