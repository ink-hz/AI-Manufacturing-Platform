import { useEffect, useRef, useState, type RefObject } from "react";
import type { OEMWorkspaceProps } from "../OEMWorkspace";
import type { MaterialProject, MaterialRequirement } from "./types";
import { useMaterialCommand } from "./useMaterialCommand";

export function MaterialTaskOpen({
  p,
  page,
  requirement,
  active,
  begin,
  resetRef,
  intent,
  onVerify,
}: {
  p: OEMWorkspaceProps;
  page: MaterialProject;
  requirement: MaterialRequirement;
  active: boolean;
  begin(f: () => void): void;
  resetRef: RefObject<() => void>;
  onVerify?(): void;
  intent?: { requirementId: string; kind: "iqc" | "trace"; reference: string; token: number } | null;
}) {
  const command = useMaterialCommand(p.api, p.project.id);
  const owner = useRef(0);
  const [version, setVersion] = useState(p.project.version);
  const [generation, setGeneration] = useState(0);
  const [kind, setKind] = useState<"iqc" | "trace" | null>(null);
  const [members, setMembers] = useState<
    { id: string; display_name: string }[]
  >([]);
  const [loading, setLoading] = useState(false),
    [member, setMember] = useState("");
  const [reference, setReference] = useState(""),
    [note, setNote] = useState("");
  const [error, setError] = useState(""),
    [saving, setSaving] = useState(false);
  useEffect(() => {
    resetRef.current = () => {
      owner.current++;
      command.clear();
      setSaving(false);
      setKind(null);
      setMembers([]);
      setMember("");
      setReference("");
      setNote("");
      setError("");
      p.onDirty("material-task-open", false);
    };
    return () => { resetRef.current = () => {}; };
  });
  const [lookup, setLookup] = useState<{ key: string; receipt?: MaterialProject["receipts"][number]; handoff?: MaterialProject["handoffs"][number]; error?: string } | null>(null);
  const receipts = page.receipts.filter((r) =>
    requirement.receipt_ids.includes(r.id),
  );
  const handoffs = page.handoffs.filter((h) =>
    requirement.handoff_ids.includes(h.id),
  );
  const lookupKey = intent && intent.requirementId === requirement.id && kind === intent.kind && reference === intent.reference
    ? JSON.stringify([p.project.id, p.project.version, requirement.id, kind, reference, intent.token]) : "";
  const previewHasReference = kind === "iqc" ? receipts.some(r => r.id === reference) : handoffs.some(h => h.id === reference);
  useEffect(() => {
    if (!active || !lookupKey || previewHasReference || !intent) return;
    const c = new AbortController();
    setLookup(null);
    const objectKind = intent.kind === "iqc" ? "receipt" : "material_handoff";
    p.api.object(p.project.id, objectKind, intent.reference, c.signal).then(detail => {
      if (c.signal.aborted) return;
      if (detail.summary.id !== intent.reference || detail.summary.project_id !== p.project.id || detail.summary.kind !== objectKind || detail.value.kind !== objectKind) throw Error("记录身份不匹配");
      if (detail.value.kind === "receipt") {
        setLookup({key: lookupKey, receipt: {id: intent.reference, quantity: detail.value.quantity, unit: detail.value.unit, qualified: detail.value.accepted, rejected: detail.value.rejected, uninspected: detail.value.uninspected}});
      } else if (detail.value.kind === "material_handoff" && detail.value.id === intent.reference) {
        setLookup({key: lookupKey, handoff: detail.value});
      } else throw Error("记录身份不匹配");
    }).catch(e => { if (!c.signal.aborted) setLookup({key: lookupKey, error: String(e)}); });
    return () => c.abort();
  }, [p.api, p.project.id, lookupKey, active, previewHasReference]);
  const currentLookup = lookup?.key === lookupKey ? lookup : null;
  const availableReceipts = currentLookup?.receipt ? [...receipts, currentLookup.receipt] : receipts;
  const availableHandoffs = currentLookup?.handoff ? [...handoffs, currentLookup.handoff] : handoffs;
  const referenceValid = kind === "iqc" ? availableReceipts.some(r => r.id === reference) : availableHandoffs.some(h => h.id === reference);
  useEffect(() => {
    if (!kind || !active) return;
    const c = new AbortController();
    setMembers([]);
    setLoading(true);
    setError("");
    p.api
      .materialAssignees(p.project.id, kind, c.signal)
      .then((v) => {
        if (!c.signal.aborted) {
          setMembers(v.items);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setError(String(e));
          setLoading(false);
        }
      });
    return () => c.abort();
  }, [p.api, p.project.id, kind, active, generation]);
  useEffect(() => {
    if (!intent || intent.requirementId !== requirement.id) return;
    command.clear(); setVersion(p.project.version); setMembers([]); setKind(intent.kind); setGeneration(n => n + 1); setMember(""); setReference(intent.reference); setNote(""); setError("");
  }, [intent?.token, requirement.id]);
  function start(next: "iqc" | "trace") {
    begin(() => {
      command.clear();
      setVersion(p.project.version);
      setMembers([]);
      setKind(next);
      setGeneration((n) => n + 1);
      setMember("");
      setReference("");
      setNote("");
      setError("");
    });
  }
  const edit = (f: (v: string) => void, v: string) => {
    f(v);
    p.onDirty("material-task-open", true);
  };
  const allowed =
    !p.readOnly && p.project.allowed_actions.includes("material_task.open");
  async function submit() {
    if (
      version !== p.project.version ||
      !allowed ||
      !kind ||
      !referenceValid ||
      !member ||
      !note.trim() ||
      saving
    )
      return;
    setSaving(true);
    setError("");
    const generation = owner.current;
    try {
      const result = await command.execute(
        {
          action: "material_task.open",
          requirement_id: requirement.id,
          task_kind: kind,
          receipt_id: kind === "iqc" ? reference : null,
          handoff_id: kind === "trace" ? reference : null,
          assignee_id: member,
          note,
        },
        version,
        result => { if (p.onMaterialChanged) p.onMaterialChanged(result); else if (command.isCurrent() && owner.current === generation) p.onChanged(result); },
      );
      if (!result || !command.isCurrent() || owner.current !== generation) return;
      p.onDirty("material-task-open", false);
      setKind(null);
    } catch (e) {
      if (command.isCurrent() && owner.current === generation) setError(String(e));
    } finally {
      if (command.isCurrent() && owner.current === generation) setSaving(false);
    }
  }
  return (
    <section>
      {allowed && (
        <div className="mf-actions">
          <button onClick={() => start("iqc")}>安排检验</button>
          <button onClick={() => start("trace")}>安排查料</button>
        </div>
      )}
      {active && kind && (
        <div>
          {version !== p.project.version && (
            <p>项目已更新，草稿已保留；请重新打开操作。</p>
          )}
          <label>
            {kind === "iqc" ? "到货记录" : "交料记录"}
            <select
              aria-label={kind === "iqc" ? "到货记录" : "交料记录"}
              value={reference}
              onChange={(e) => edit(setReference, e.target.value)}
            >
              <option value="">请选择</option>
              {kind === "iqc"
                ? availableReceipts.map((r, i) => (
                    <option key={r.id} value={r.id}>
                      到货 {i + 1} · {r.quantity} {r.unit} · 待检{" "}
                      {r.uninspected} {r.unit}
                    </option>
                  ))
                : availableHandoffs.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.handoff_number} · {h.quantity} {h.unit} ·{" "}
                      {h.from_location} → {h.to_location}
                    </option>
                  ))}
            </select>
          </label>
          {!(kind === "iqc" ? availableReceipts : availableHandoffs).length && !lookupKey && (
            <p>
              {kind === "iqc" ? <>没有关联到货记录，请先登记到货。 {onVerify && <button data-arrange-verification onClick={onVerify}>安排核实</button>}</> : "没有关联交料记录，请先登记交料。"}
            </p>
          )}
          {lookupKey && !previewHasReference && !currentLookup && <p role="status">正在读取关联记录…</p>}
          {currentLookup?.error && <p role="alert">关联记录读取失败：{currentLookup.error}</p>}
          {loading && <p role="status">正在读取可选成员…</p>}
          <label>
            {kind === "iqc" ? "检验人" : "查料人"}
            <select
              aria-label={kind === "iqc" ? "检验人" : "查料人"}
              value={member}
              disabled={loading}
              onChange={(e) => edit(setMember, e.target.value)}
            >
              <option value="">请选择</option>
              {members.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            任务说明
            <input
              aria-label="任务说明"
              value={note}
              onChange={(e) => edit(setNote, e.target.value)}
            />
          </label>
          {error && <p role="alert">成员或任务读取失败：{error}</p>}
          <button
            disabled={
              saving ||
              loading ||
              version !== p.project.version ||
              !allowed ||
              !referenceValid ||
              !member ||
              !note.trim()
            }
            onClick={() => void submit()}
          >
            创建任务
          </button>
        </div>
      )}
    </section>
  );
}
