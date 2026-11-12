type History = {
  action: string;
  actor_name: string;
  recorded_at?: string;
  note?: string | null;
  reason?: string | null;
  evidence?: string | null;
  outcome?: string | null;
  blocked_reason?: string | null;
  assignee_id?: string | null;
  expected_completion?: string | null;
  found_quantity?: string | null;
  found_location?: string | null;
};
const actions: Record<string, string> = {
  open: "创建",
  accept: "接单",
  progress: "更新进展",
  verify: "核验",
  close: "完成",
  cancel: "取消",
  reassign: "转交",
};
const outcomes: Record<string, string> = {
  fulfilled: "已完成",
  discrepancy: "存在差异",
  false_alarm: "误报",
  superseded: "已替代",
  identity_verified: "身份已核实",
  unable_to_verify: "无法核实",
  incorrect_observation: "观察有误",
};
export function MaterialTaskHistory({
  history,
  unit,
  members = [],
}: {
  history: History[];
  unit: string;
  members?: { id: string; display_name: string }[];
}) {
  if (!history.length) return null;
  return (
    <details>
      <summary>任务记录（{history.length}）</summary>
      {history.map((h, i) => (
        <p key={i}>
          {h.recorded_at} · {h.actor_name} · {actions[h.action] || h.action}
          {h.assignee_id &&
            ` · 指派：${members.find((m) => m.id === h.assignee_id)?.display_name || "成员资料不可用"}`}
          {h.note && ` · ${h.note}`}
          {h.reason && ` · 原因：${h.reason}`}
          {h.evidence && ` · 说明：${h.evidence}`}
          {h.outcome && ` · 结果：${outcomes[h.outcome] || h.outcome}`}
          {h.blocked_reason && ` · 阻碍：${h.blocked_reason}`}
          {h.expected_completion && ` · 预计 ${h.expected_completion}`}
          {h.found_quantity &&
            ` · 找到 ${h.found_quantity} ${unit || "单位未提供"} ${h.found_location || ""}`}
        </p>
      ))}
    </details>
  );
}
