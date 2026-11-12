import { WorkflowError } from "../api";
import { MaterialReferenceOpen } from "./MaterialReferenceOpen";
import type { WorkflowTarget } from "../types";
import { MaterialReferenceContext } from "./MaterialReferenceContext";
import { VerificationFields, type VerificationOutcome } from "./VerificationFields";
import type { MaterialTaskValue } from "./types";
import { MesIqcResults } from "./MesIqcResults";
import { MaterialTaskContext } from "./MaterialTaskContext";
import { MaterialTaskHistory } from "./MaterialTaskHistory";
import { useMaterialCommand } from "./useMaterialCommand";
import { useEffect, useRef, useState } from "react";
import type { WorkflowApi } from "../api";
import type {
  CommandFields,
  MutationAcknowledgement,
  ProjectDetail,
} from "../types";
import type { MaterialProject } from "./types";
type Detail = {
  summary: { title: string; next_actions: string[] };
  value: MaterialTaskValue;
};
type Props = {
  api: WorkflowApi;
  project: ProjectDetail;
  taskId: string;
  readOnly: boolean;
  onChanged(v: MutationAcknowledgement): void;
  onMaterialChanged?(v: MutationAcknowledgement): void;
  onOpen?(target: WorkflowTarget): void;
  onDirty(key: string, dirty: boolean): void;
  requestLeave?(action: () => void): void;
};
export function MaterialTaskPanel(p: Props) {
  const command = useMaterialCommand(p.api, p.project.id);
  const revision = useRef(0);
  const resetReference = useRef<() => void>(() => {});
  const handoffRequest = useRef(0);
  const [conflict, setConflict] = useState(false);
  const authority = useRef({ version: p.project.version, readOnly: p.readOnly, actions: p.project.allowed_actions.join("|") });
  const nextAuthority = { version: p.project.version, readOnly: p.readOnly, actions: p.project.allowed_actions.join("|") };
  if (JSON.stringify(authority.current) !== JSON.stringify(nextAuthority)) {
    authority.current = nextAuthority;
    revision.current++;
  }
  useEffect(() => { revision.current++; return () => { revision.current++; }; }, [p.api, p.project.id, p.taskId]);
  const [verifyOutcome, setVerifyOutcome] = useState<VerificationOutcome>("identity_verified");
  const [adopted, setAdopted] = useState(false);
  const [version, setVersion] = useState(p.project.version);
  const [detail, setDetail] = useState<Detail | null>(null),
    [error, setError] = useState(""),
    [form, setForm] = useState<
      "progress" | "close" | "cancel" | "reassign" | "inspect" | null
    >(null),
    [text, setText] = useState(""),
    [deadline, setDeadline] = useState(""),
    [blocked, setBlocked] = useState(""),
    [found, setFound] = useState(""),
    [location, setLocation] = useState(""),
    [assignee, setAssignee] = useState(""),
    [members, setMembers] = useState<
      {
        id: string;
        display_name: string;
      }[]
    >([]),
    [outcome, setOutcome] = useState<
      "fulfilled" | "discrepancy" | "false_alarm" | "superseded"
    >("fulfilled"),
    [saving, setSaving] = useState(false),
    [accepted, setAccepted] = useState(""),
    [rejected, setRejected] = useState(""),
    [inspectAllowed, setInspectAllowed] = useState(false),
    [handoffs, setHandoffs] = useState<MaterialProject["handoffs"]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [unit, setUnit] = useState(""),
    [receiptUnit, setReceiptUnit] = useState(""),
    [handoffOffset, setHandoffOffset] = useState(0),
    [handoffTotal, setHandoffTotal] = useState<number | null>(null),
    [handoffBusy, setHandoffBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const c = new AbortController();
    setDetail(null);
    setError("");
    p.api
      .object(p.project.id, "material_task", p.taskId, c.signal)
      .then((d) => {
        if (active) setDetail(d as unknown as Detail);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [p.api, p.project.id, p.project.version, p.taskId]);
  useEffect(() => {
    if (!detail?.value.receipt_id || detail.value.task_kind !== "iqc") return;
    let active = true;
    const c = new AbortController();
    setInspectAllowed(false);
    p.api
      .object(p.project.id, "receipt", detail.value.receipt_id, c.signal)
      .then((v) => {
        if (active)
          setInspectAllowed(v.summary.next_actions.includes("supply.inspect"));
      })
      .catch(() => {
        if (active) setInspectAllowed(false);
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [p.api, p.project.id, detail?.value.receipt_id, detail?.value.task_kind]);
  useEffect(() => {
    if (!detail) return;
    let active = true;
    const c = new AbortController();
    if (p.api.materialAssignees)
      p.api
        .materialAssignees(p.project.id, detail.value.task_kind, c.signal)
        .then((v) => {
          if (active) setMembers(v.items);
        })
        .catch(() => {});
    if (detail.value.requirement_id && p.api.materialRequirement)
      p.api
        .materialRequirement(
          p.project.id,
          detail.value.requirement_id,
          c.signal,
        )
        .then((v) => {
          if (active) {
            setHandoffs((old) => [
              ...new Map(
                [...old, ...v.handoffs].map((h) => [h.id, h]),
              ).values(),
            ]);
            setUnit(
              v.requirements?.find((r) => r.id === detail.value.requirement_id)
                ?.unit || "",
            );
          }
        })
        .catch(() => {});
    return () => {
      active = false;
      c.abort();
    };
  }, [
    p.api,
    p.project.id,
    detail?.value.requirement_id,
    detail?.value.task_kind,
  ]);
  useEffect(() => {
    if (!detail?.value.handoff_id) return;
    let active = true;
    const c = new AbortController();
    p.api
      .object(
        p.project.id,
        "material_handoff",
        detail.value.handoff_id,
        c.signal,
      )
      .then((d) => {
        if (active && d.value.kind === "material_handoff") {
          const handoff = d.value;
          setHandoffs((old) => {
            const m = new Map(old.map((h) => [h.id, h]));
            m.set(handoff.id, handoff);
            return [...m.values()];
          });
        }
      })
      .catch(() => {});
    return () => {
      active = false;
      c.abort();
    };
  }, [p.api, p.project.id, detail?.value.handoff_id]);
  const can = (action: string) =>
    !p.readOnly &&
    !!detail?.summary.next_actions.includes(action) &&
    p.project.allowed_actions.some((x) => x === action);
  function start(f: typeof form) {
    (p.requestLeave || ((fn: () => void) => fn()))(() => {
      revision.current++;
      command.clear();
      setVersion(p.project.version);
      setConflict(false);
      setForm(f);
      setText("");
      setDeadline("");
      setBlocked("");
      setFound("");
      setLocation("");
      setAccepted("");
      setRejected("");
      setAssignee("");
      setOutcome("fulfilled");
      setVerifyOutcome("identity_verified"); setAdopted(false);
      setSelected([]);
      setError("");

    });
  }
  async function send(fields: CommandFields) {
    if (saving) return;
    setSaving(true);
    setError("");
    const token = revision.current;
    try {
      const result = await command.execute(
        fields,
        form ? version : p.project.version,
        result => {
          if (p.onMaterialChanged) p.onMaterialChanged(result);
          else if (command.isCurrent() && revision.current === token) p.onChanged(result);
        },
      );
      if (!result || revision.current !== token) return;
      p.onDirty("material-task", false);
      setForm(null);
    } catch (e) {
      if (command.isCurrent() && revision.current === token) {
        setError(String(e));
        if (e instanceof WorkflowError && (e.code === "VERSION_CONFLICT" || e.code === "REFERENCE_STALE"))
          setConflict(true);
      }
    } finally {
      if (command.isCurrent()) setSaving(false);
    }
  }
  async function moreHandoffs() {
    if (handoffBusy || typeof p.api.objects !== "function") return;
    setHandoffBusy(true);
    const token = revision.current;
    const request = ++handoffRequest.current;
    try {
      const page = await p.api.objects(
        p.project.id,
        "material_handoff",
        50,
        handoffOffset,
      );
      const rows = await Promise.all(
        page.items.map((item) =>
          p.api.object(p.project.id, "material_handoff", item.id),
        ),
      );
      if (!command.isCurrent() || token !== revision.current) return;
      setHandoffs((old) => {
        const map = new Map(old.map((v) => [v.id, v]));
        for (const row of rows)
          if (row.value.kind === "material_handoff")
            map.set(row.value.id, row.value);
        return [...map.values()];
      });
      setHandoffOffset(handoffOffset + page.items.length);
      setHandoffTotal(page.total);
    } catch (e) {
      if (command.isCurrent() && token === revision.current) setError(String(e));
    } finally {
      if (command.isCurrent() && request === handoffRequest.current) setHandoffBusy(false);
    }
  }
  const origin = handoffs.find((h) => h.id === detail?.value.handoff_id);
  const candidates = origin
    ? handoffs.filter(
        (h) =>
          h.id !== origin.id &&
          h.receipt &&
          h.material_lot_id === origin.material_lot_id &&
          h.work_order_id === origin.work_order_id &&
          h.receiver_id === origin.receiver_id &&
          h.unit === origin.unit &&
          h.receipt.received_location === origin.to_location,
      )
    : [];
  const edit = (f: (v: string) => void, v: string) => {
    revision.current++;
    f(v);
    p.onDirty("material-task", true);
  };
  const formAllowed =
    !!form &&
    version === p.project.version && !conflict &&
    (form === "inspect"
      ? !p.readOnly &&
        inspectAllowed &&
        p.project.allowed_actions.includes("supply.inspect")
      : can("material_task." + form));
  function submit() {
    if (!form || !formAllowed || !text.trim()) return;
    const task_id = p.taskId;
    if (form === "inspect" && detail?.value.receipt_id)
      void send({
        action: "supply.inspect",
        receipt_id: detail.value.receipt_id,
        accepted,
        rejected,
        evidence: text,
      });
    else if (form === "progress")
      void send({
        action: "material_task.progress",
        task_id,
        note: text,
        expected_completion: deadline ? new Date(deadline).toISOString() : null,
        blocked_reason: blocked || null,
        found_quantity: found || null,
        found_location: location || null,
      });
    else if (form === "close")
      void send({
        action: "material_task.close",
        task_id,
        outcome: detail?.value.task_kind === "verify" ? verifyOutcome : outcome,
        evidence: text,
        ...(detail?.value.task_kind === "verify"
          ? { resolved_reference: verifyOutcome === "identity_verified" && adopted ? detail.value.current_reference : null }
          : { handoff_ids: selected }),
      });
    else if (form === "cancel")
      void send({ action: "material_task.cancel", task_id, reason: text });
    else if (assignee)
      void send({
        action: "material_task.reassign",
        task_id,
        assignee_id: assignee,
        reason: text,
      });
  }
  return (
    <section aria-label="物料任务">
      <h3>{detail?.value.task_kind === "iqc" ? "来料检验任务" : detail?.value.task_kind === "verify" ? "物料核实任务" : "查料任务"}</h3>
      {error && <p role="alert">{error}</p>}
      {!detail && !error && <p role="status">正在读取任务…</p>}
      {detail && (
        <>
          <p>{detail.value.note}</p>
          {detail.value.assignee_id && (
            <p>
              负责人：
              {members.find((m) => m.id === detail.value.assignee_id)
                ?.display_name || "成员资料不可用"}
              {detail.value.proposed_assignee_id &&
                ` · 待接收：${members.find((m) => m.id === detail.value.proposed_assignee_id)?.display_name || "成员资料不可用"}`}
            </p>
          )}
          <p>
            状态：
            {(
              {
                pending: "待接单",
                processing: "处理中",
                verification: "待完成",
                closed: "已完成",
                cancelled: "已取消",
              } as Record<string, string>
            )[detail.value.state] || detail.value.state}
          </p>
          {detail.value.reference && <MaterialReferenceContext
            api={p.api} projectId={p.project.id} projectVersion={p.project.version} evidence={detail.value.reference}
            current={detail.value.reference_current} currentReference={detail.value.current_reference}
            issue={detail.value.reference_issue}
            renderCurrentReceipt={detail.value.task_kind === "verify" && p.onOpen ? receiptId =>
              <MaterialReferenceOpen key={receiptId}
                p={{ api: p.api, project: p.project, readOnly: p.readOnly, onChanged: p.onChanged,
                  onMaterialChanged: p.onMaterialChanged, onDirty: p.onDirty, onOpen: p.onOpen!,
                  requestLeave: p.requestLeave || (f => f()) }}
                fixedReceiptId={receiptId} resetRef={resetReference}
              /> : undefined}
          />}
          {(detail.value.receipt_id || detail.value.handoff_id) && <MaterialTaskContext
            api={p.api}
            projectId={p.project.id}
            receiptId={detail.value.receipt_id}
            handoffId={detail.value.handoff_id}
            version={p.project.version}
            onReceipt={(d) => {
              if (d.value?.kind === "receipt") setReceiptUnit(d.value.unit);
            }}
          />}
          {detail.value.receipt_id && receiptUnit && (
            <MesIqcResults
              api={p.api}
              project={p.project}
              receiptId={detail.value.receipt_id}
              unit={receiptUnit}
              readOnly={p.readOnly}
              onChanged={p.onChanged}
            />
          )}
          {detail.value.task_kind === "verify" && detail.value.reference?.reference.kind !== "arrival" && detail.value.reference_current === true && detail.value.reference?.receipt_id && p.onOpen &&
            <MaterialReferenceOpen
              p={{ api: p.api, project: p.project, readOnly: p.readOnly, onChanged: p.onChanged,
                onMaterialChanged: p.onMaterialChanged, onDirty: p.onDirty, onOpen: p.onOpen,
                requestLeave: p.requestLeave || (f => f()) }}
              fixedReceiptId={detail.value.reference.receipt_id} resetRef={resetReference}
            />}
          <MaterialTaskHistory
            history={detail.value.history}
            unit={unit}
            members={members}
          />
          <div className="mf-actions">
            {!p.readOnly &&
              detail.value.task_kind === "iqc" &&
              inspectAllowed &&
              p.project.allowed_actions.includes("supply.inspect") && (
                <button onClick={() => start("inspect")}>登记检验结果</button>
              )}
            {can("material_task.accept") && (
              <button
                disabled={saving}
                onClick={() =>
                  (p.requestLeave || ((fn: () => void) => fn()))(
                    () =>
                      void send({
                        action: "material_task.accept",
                        task_id: p.taskId,
                      }),
                  )
                }
              >
                接单
              </button>
            )}
            {can("material_task.progress") && (
              <button onClick={() => start("progress")}>更新进展</button>
            )}
            {can("material_task.close") && (
              <button onClick={() => start("close")}>完成任务</button>
            )}
            {can("material_task.reassign") && (
              <button onClick={() => start("reassign")}>转交任务</button>
            )}
            {can("material_task.cancel") && (
              <button onClick={() => start("cancel")}>取消任务</button>
            )}
          </div>
          {form && (
            <div>
              {version !== p.project.version && (
                <p>项目已更新，草稿已保留；请重新打开操作。</p>
              )}
              <label>
                {form === "progress"
                  ? "进展"
                  : form === "close"
                    ? "完成说明"
                    : form === "inspect"
                      ? "检验说明"
                      : "原因"}
                <input
                  aria-label={
                    form === "progress"
                      ? "进展"
                      : form === "close"
                        ? "完成说明"
                        : form === "inspect"
                          ? "检验说明"
                          : "原因"
                  }
                  value={text}
                  onChange={(e) => edit(setText, e.target.value)}
                />
              </label>
              {form === "inspect" && (
                <>
                  <label>
                    合格数量 {receiptUnit || unit}
                    <input
                      aria-label="合格数量"
                      value={accepted}
                      onChange={(e) => edit(setAccepted, e.target.value)}
                    />
                  </label>
                  <label>
                    拒收数量 {receiptUnit || unit}
                    <input
                      aria-label="拒收数量"
                      value={rejected}
                      onChange={(e) => edit(setRejected, e.target.value)}
                    />
                  </label>
                </>
              )}
              {form === "progress" && (
                <>
                  <label>
                    预计完成
                    <input
                      type="datetime-local"
                      aria-label="预计完成"
                      value={deadline}
                      onChange={(e) => edit(setDeadline, e.target.value)}
                    />
                  </label>
                  <label>
                    阻碍原因
                    <input
                      aria-label="阻碍原因"
                      value={blocked}
                      onChange={(e) => edit(setBlocked, e.target.value)}
                    />
                  </label>
                  {detail.value.task_kind === "trace" && (
                    <>
                      <label>
                        找到数量 {unit || "单位未提供"}
                        <input
                          aria-label="找到数量"
                          value={found}
                          onChange={(e) => edit(setFound, e.target.value)}
                        />
                      </label>
                      <label>
                        找到位置
                        <input
                          aria-label="找到位置"
                          value={location}
                          onChange={(e) => edit(setLocation, e.target.value)}
                        />
                      </label>
                    </>
                  )}
                </>
              )}
              {form === "close" && detail.value.task_kind === "trace" && (
                <fieldset>
                  <legend>补充已签收交料</legend>
                  <p>
                    短少或未签收时请更新进展并继续查料；实际签收完整后才能完成任务。
                  </p>
                  {candidates.map((h) => (
                    <label key={h.id}>
                      <input
                        type="checkbox"
                        checked={selected.includes(h.id)}
                        onChange={(e) => {
                          revision.current++;
                          setSelected((old) =>
                            e.target.checked
                              ? [...old, h.id]
                              : old.filter((id) => id !== h.id),
                          );
                          p.onDirty("material-task", true);
                        }}
                      />
                      {h.handoff_number} · 实收 {h.receipt?.received_quantity}{" "}
                      {h.unit} · {h.receipt?.received_location}
                    </label>
                  ))}
                  {!candidates.length && (
                    <p>当前读取范围没有匹配的签收记录。</p>
                  )}
                  {handoffTotal !== null && (
                    <p>
                      已读取 {handoffOffset} / {handoffTotal} 条交料记录。
                    </p>
                  )}
                  {typeof p.api.objects === "function" &&
                    (handoffTotal === null || handoffOffset < handoffTotal) && (
                      <button
                        disabled={handoffBusy}
                        onClick={() => void moreHandoffs()}
                      >
                        查找更多签收记录
                      </button>
                    )}
                </fieldset>
              )}
              {form === "close" && detail.value.task_kind === "verify" && <VerificationFields
                outcome={verifyOutcome}
                onOutcome={v => { revision.current++; setVerifyOutcome(v); p.onDirty("material-task", true); }}
                current={detail.value.reference_current} currentReference={detail.value.current_reference}
                adopted={adopted}
                onAdopt={v => { revision.current++; setAdopted(v); p.onDirty("material-task", true); }}
              />}
              {form === "close" && detail.value.task_kind !== "verify" && (
                <label>
                  结果
                  <select
                    aria-label="结果"
                    value={outcome}
                    onChange={(e) =>
                      edit(
                        (v) => setOutcome(v as typeof outcome),
                        e.target.value,
                      )
                    }
                  >
                    <option value="fulfilled">已完成</option>
                    <option value="discrepancy">存在差异</option>
                    <option value="false_alarm">误报</option>
                    <option value="superseded">已替代</option>
                  </select>
                </label>
              )}
              {form === "reassign" && (
                <label>
                  接收人
                  <select
                    aria-label="接收人"
                    value={assignee}
                    onChange={(e) => edit(setAssignee, e.target.value)}
                  >
                    <option value="">请选择</option>
                    {members.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.display_name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                disabled={
                  saving ||
                  !formAllowed ||
                  !text.trim() ||
                  (form === "close" && detail.value.task_kind === "verify" && verifyOutcome === "identity_verified" && detail.value.reference_current !== true && (!detail.value.current_reference || !adopted)) ||
                  (form === "reassign" && !assignee) ||
                  (form === "inspect" && (!accepted || !rejected))
                }
                onClick={submit}
              >
                提交
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
