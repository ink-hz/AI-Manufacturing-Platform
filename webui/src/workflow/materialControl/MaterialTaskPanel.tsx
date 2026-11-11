import { MesIqcResults } from "./MesIqcResults";
import { MaterialTaskContext } from "./MaterialTaskContext";
import { MaterialTaskHistory } from "./MaterialTaskHistory";
import { useMaterialCommand } from "./useMaterialCommand";
import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import type {
  CommandFields,
  MutationAcknowledgement,
  ProjectDetail,
} from "../types";
import type { MaterialProject } from "./types";
type Detail = {
  summary: {
    title: string;
    next_actions: string[];
  };
  value: {
    task_kind: "iqc" | "trace";
    state: string;
    note: string;
    assignee_id: string;
    proposed_assignee_id: string | null;
    requirement_id: string;
    receipt_id: string | null;
    handoff_id: string | null;
    history: {
      action: string;
      actor_name: string;
      note: string | null;
      expected_completion: string | null;
      found_quantity: string | null;
      found_location: string | null;
    }[];
  };
};
type Props = {
  api: WorkflowApi;
  project: ProjectDetail;
  taskId: string;
  readOnly: boolean;
  onChanged(v: MutationAcknowledgement): void;
  onDirty(key: string, dirty: boolean): void;
  requestLeave?(action: () => void): void;
};
export function MaterialTaskPanel(p: Props) {
  const command = useMaterialCommand(p.api, p.project.id);
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
      command.clear();
      setVersion(p.project.version);
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
      setSelected([]);
      setError("");
      if (f === "close" && detail?.value.task_kind === "trace")
        p.api
          .materialRequirement(p.project.id, detail.value.requirement_id)
          .then((v) =>
            setHandoffs((old) => [
              ...new Map(
                [...old, ...v.handoffs].map((h) => [h.id, h]),
              ).values(),
            ]),
          )
          .catch((e) => setError(String(e)));
      if (f === "reassign" && detail)
        p.api
          .materialAssignees(p.project.id, detail.value.task_kind)
          .then((x) => setMembers(x.items))
          .catch((e) => setError(String(e)));
    });
  }
  async function send(fields: CommandFields) {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      const result = await command.execute(
        fields,
        form ? version : p.project.version,
      );
      if (!result) return;
      p.onDirty("material-task", false);
      setForm(null);
      p.onChanged(result);
    } catch (e) {
      if (command.isCurrent()) setError(String(e));
    } finally {
      if (command.isCurrent()) setSaving(false);
    }
  }
  async function moreHandoffs() {
    if (handoffBusy || typeof p.api.objects !== "function") return;
    setHandoffBusy(true);
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
      setError(String(e));
    } finally {
      setHandoffBusy(false);
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
    f(v);
    p.onDirty("material-task", true);
  };
  const formAllowed =
    !!form &&
    version === p.project.version &&
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
        outcome,
        evidence: text,
        handoff_ids: selected,
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
      <h3>{detail?.value.task_kind === "iqc" ? "来料检验任务" : "查料任务"}</h3>
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
          <MaterialTaskContext
            api={p.api}
            projectId={p.project.id}
            receiptId={detail.value.receipt_id}
            handoffId={detail.value.handoff_id}
            version={p.project.version}
            onReceipt={(d) => {
              if (d.value?.kind === "receipt") setReceiptUnit(d.value.unit);
            }}
          />
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
              {form === "close" && (
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
