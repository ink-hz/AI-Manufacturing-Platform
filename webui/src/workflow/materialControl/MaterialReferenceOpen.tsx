import { useEffect, useRef, useState, type RefObject } from "react";
import { WorkflowError } from "../api";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import type { TaskReferenceItem, TaskReference } from "./types";
import { validateReferencePage } from "./api";
import { ArrivalObservationForm } from "./ArrivalObservationForm";
import { MaterialReferenceContext } from "./MaterialReferenceContext";
import { MaterialReferencePicker } from "./MaterialReferencePicker";
import { useMaterialCommand } from "./useMaterialCommand";

type Intent = { token: number; reference?: TaskReference; search?: string; requirementId?: string };
export function MaterialReferenceOpen({ p, intent, resetRef, fixedReceiptId }: {
  p: OEMWorkspaceProps; intent?: Intent | null; resetRef: RefObject<() => void>; fixedReceiptId?: string;
}) {
  const [requirementId, setRequirementId] = useState<string>();
  const [observation, setObservation] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [kind, setKind] = useState<"verify" | "iqc">("verify");
  const [open, setOpen] = useState(false);
  const [item, setItem] = useState<TaskReferenceItem | null>(null);
  const [version, setVersion] = useState(p.project.version);
  const [member, setMember] = useState("");
  const [note, setNote] = useState("");
  const [members, setMembers] = useState<{ id: string; display_name: string }[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const generation = useRef(0);
  const operation = useRef(0);
  const command = useMaterialCommand(p.api, p.project.id);
  const identity = useRef({ api: p.api, projectId: p.project.id });
  const sameIdentity = identity.current.api === p.api && identity.current.projectId === p.project.id;
  if (!sameIdentity) {
    identity.current = { api: p.api, projectId: p.project.id };
    generation.current++;
  }
  const allowed = !p.readOnly && p.project.allowed_actions.includes("material_task.open");
  const authority = useRef({ allowed, version: p.project.version });
  if (authority.current.allowed !== allowed || authority.current.version !== p.project.version) {
    authority.current = { allowed, version: p.project.version };
    generation.current++;
  }
  useEffect(() => {
    resetRef.current = () => {
      generation.current++;
      operation.current++;
      command.clear();
      setOpen(false); setObservation(false); setItem(null); setMember(""); setNote("");
      setError(""); setSaving(false);
      p.onDirty("material-reference-open", false);
      p.onDirty("arrival-observation", false);
    };
    return () => { resetRef.current = () => {}; };
  });
  useEffect(() => {
    generation.current++;
    setOpen(false); setItem(null); setMember(""); setNote(""); setSaving(false);
    return () => { generation.current++; };
  }, [p.api, p.project.id]);
  useEffect(() => {
    if (!open) return;
    const c = new AbortController();
    setMembers([]);
    if (typeof p.api.materialAssignees !== "function") {
      setError("成员查询不可用");
      return () => c.abort();
    }
    p.api.materialAssignees(p.project.id, kind, c.signal)
      .then(v => { if (!c.signal.aborted) setMembers(v.items); })
      .catch(e => { if (!c.signal.aborted) setError(String(e)); });
    return () => c.abort();
  }, [p.api, p.project.id, open, kind]);
  useEffect(() => {
    if (!intent) return;
    generation.current++;
    setKind("verify"); setRequirementId(intent.requirementId); setObservation(false);
    setVersion(p.project.version); setOpen(true); setItem(null); setMember(""); setNote(""); setError(""); setConflict(false);
  }, [intent?.token]);
  useEffect(() => {
    if (!intent?.reference || typeof p.api.materialReferences !== "function") return;
    const c = new AbortController();
    const token = generation.current;
    const wanted = JSON.stringify(intent.reference);
    (async () => {
      for (let offset = 0; offset < 1000; offset += 50) {
        const page = validateReferencePage(await p.api.materialReferences(p.project.id, "verify", intent.search || "", 50, offset, c.signal), p.project.id, "verify");
        if (c.signal.aborted || token !== generation.current) return;
        const found = page.items.find(i => JSON.stringify(i.reference) === wanted);
        if (found) {
          setItem(found); setVersion(page.project_version);
          p.onDirty("material-reference-open", true);
          return;
        }
        if (offset + page.items.length >= page.total || !page.items.length) break;
      }
      if (!c.signal.aborted && token === generation.current)
        setError("组件引用已变化或不在当前读取范围，请重新选择。");
    })().catch(e => { if (!c.signal.aborted && token === generation.current) setError(String(e)); });
    return () => c.abort();
  }, [p.api, p.project.id, intent?.token]);
  useEffect(() => {
    if (!fixedReceiptId || !open || kind !== "iqc") return;
    setItem(null);
    setError("");
    if (!allowed) return;
    if (typeof p.api.materialReferences !== "function") { setError("引用查询不可用"); return; }
    const c = new AbortController();
    p.api.materialReferences(p.project.id, "iqc", "", 1, 0, c.signal, undefined, { receipt_id: fixedReceiptId })
      .then(result => {
        if (c.signal.aborted) return;
        const page = validateReferencePage(result, p.project.id, "iqc");
        if (page.items.some(i => i.evidence.receipt_id !== fixedReceiptId)) throw Error("收货引用身份不匹配");
        const found = page.items[0];
        if (!found) { setError("当前收货不在可检验引用中。"); return; }
        setItem(found); setVersion(page.project_version);
      }).catch(e => { if (!c.signal.aborted) setError(String(e)); });
    return () => c.abort();
  }, [p.api, p.project.id, p.project.version, fixedReceiptId, open, kind, allowed, refresh]);
  function select(value: TaskReferenceItem, pageVersion: number) {
    generation.current++;
    setItem(value); setVersion(pageVersion); setError(""); setConflict(false);
    p.onDirty("material-reference-open", true);
  }
  async function submit() {
    if (!item || !item.can_open || !member || !note.trim() || !allowed || version !== p.project.version || saving || conflict) return;
    const token = generation.current;
    const op = ++operation.current;
    setSaving(true); setError("");
    try {
      const result = await command.execute({
        action: "material_task.open", task_kind: kind, reference: item.reference,
        ...(requirementId ? { requirement_id: requirementId } : {}), assignee_id: member, note,
      }, version, result => {
        if (p.onMaterialChanged) p.onMaterialChanged(result);
        else if (command.isCurrent() && token === generation.current) p.onChanged(result);
      });
      if (result && command.isCurrent() && token === generation.current) {
        p.onDirty("material-reference-open", false);
        setOpen(false); setItem(null);
        p.onOpen({ projectId: p.project.id, kind: "material_task", id: result.object_id });
      }
    } catch (e) {
      if (command.isCurrent() && token === generation.current) {
        setError(String(e));
        if (e instanceof WorkflowError && (e.code === "VERSION_CONFLICT" || e.code === "REFERENCE_STALE")) setConflict(true);
      }
    } finally {
      if (command.isCurrent() && op === operation.current) setSaving(false);
    }
  }
  function start(next: "verify" | "iqc") {
    p.requestLeave(() => {
      generation.current++;
      setRefresh(n => n + 1);
      setKind(next); setRequirementId(undefined); setObservation(false); setVersion(p.project.version);
      setOpen(true); setItem(null); setMember(""); setNote(""); setError(""); setConflict(false);
    });
  }
  return <section>
    {allowed && (fixedReceiptId
      ? <button onClick={() => start("iqc")}>为关联收货安排检验</button>
      : <><button onClick={() => start("verify")}>安排核实</button><button onClick={() => start("iqc")}>从已有收货安排检验</button></>)}
    {sameIdentity && open && <>
      {kind === "verify" && p.project.allowed_actions.includes("arrival.record") && !p.readOnly &&
        <button onClick={() => setObservation(true)}>记录实际包裹</button>}
      {observation && <ArrivalObservationForm p={p} onRecorded={() => { setObservation(false); setRefresh(n => n + 1); }} />}
      {!fixedReceiptId && <MaterialReferencePicker api={p.api} key={kind + ":" + refresh} projectId={p.project.id}
        version={p.project.version} kind={kind} requirementId={requirementId} onSelect={select} />}
      {item && <>
        <p>已选择：{item.evidence.title}</p>
        <MaterialReferenceContext api={p.api} projectId={p.project.id} projectVersion={p.project.version} evidence={item.evidence} current={null} currentReference={null} issue={null} />
        {item.existing_task_id
          ? <button onClick={() => p.requestLeave(() => p.onOpen({ projectId: p.project.id, kind: "material_task", id: item.existing_task_id! }))}>打开已有任务</button>
          : <>
            <label>{kind === "verify" ? "核实人" : "检验人"}
              <select aria-label={kind === "verify" ? "核实人" : "检验人"} value={member} onChange={e => { generation.current++; setMember(e.target.value); p.onDirty("material-reference-open", true); }}>
                <option value="">请选择</option>{members.map(m => <option key={m.id} value={m.id}>{m.display_name}</option>)}
              </select>
            </label>
            <label>任务说明<input aria-label="核实任务说明" value={note} onChange={e => { generation.current++; setNote(e.target.value); p.onDirty("material-reference-open", true); }} /></label>
            <button disabled={!allowed || !item.can_open || version !== p.project.version || !member || !note.trim() || saving || conflict} onClick={() => void submit()}>{kind === "verify" ? "创建核实任务" : "创建检验任务"}</button>
          </>}
      </>}
      {version !== p.project.version && <p>项目已更新，草稿已保留；请重新选择引用。</p>}
      {error && <p role="alert">操作失败：{error}</p>}
    </>}
  </section>;
}
