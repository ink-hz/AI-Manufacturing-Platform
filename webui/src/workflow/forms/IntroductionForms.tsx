import type { OEMCommands, ReviewCheck } from "../types";
import { CommandForm, Field, Choice } from "./shared";
import {
  type OEMFormProps,
  Pick,
  ManyObjects,
  Names,
  Toggle,
  decisions,
  selected,
  useSelected,
} from "./oemShared";
type Command<A extends OEMCommands["action"]> = Extract<
  OEMCommands,
  { action: A }
>;
const check = (): ReviewCheck => ({
  code: "",
  required: true,
  decision: "blocked",
  evidence: "",
  reason: "",
});
export function IntroductionForms(p: OEMFormProps) {
  const selection = useSelected(p);
  if (p.action === "npi.open")
    return (
      <CommandForm<Command<"npi.open">>
        {...p}
        title="创建工程导入"
        save="保存工程导入"
        initial={() => ({
          action: "npi.open",
          revision_id: selected(p, "revision"),
          product_family: "",
          scenario: "first_introduction",
          required_checks: [""],
          work_order_ids: [],
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="revision"
              name="导入固定修订"
              value={v.revision_id}
              onChange={(x) => set({ ...v, revision_id: x })}
            />
            <Field
              name="产品族"
              value={v.product_family}
              onChange={(x) => set({ ...v, product_family: x })}
            />
            <Choice
              name="导入场景"
              value={v.scenario}
              choices={{
                first_introduction: "首次导入",
                change_validation: "变更验证",
              }}
              onChange={(x) => set({ ...v, scenario: x as typeof v.scenario })}
            />
            <Names
              name="必需检查项"
              value={v.required_checks}
              onChange={(x) => set({ ...v, required_checks: x })}
            />
            <ManyObjects
              name="参与工单"
              items={p.items.work_order || []}
              value={v.work_order_ids}
              onChange={(x) => set({ ...v, work_order_ids: x })}
            />
            <p>只将明确选择的工单纳入当前导入约束。</p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "npi.review")
    return (
      <CommandForm<Command<"npi.review">>
        {...p}
        title="记录导入评审"
        save="保存导入评审"
        initial={() => ({
          action: "npi.review",
          npi_id: "",
          checks: [check()],
        })}
        canSubmit={(v) => !!v.npi_id && !selection.loading}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="npi"
              name="评审导入"
              value={v.npi_id}
              onChange={(x) => {
                set({ ...v, npi_id: x });
                void selection.read("npi", x, (d) => {
                  if (d.value.kind === "npi") {
                    const checks = d.value.required_checks.map((code) => ({
                      ...check(),
                      code,
                    }));
                    set((old) => (old.npi_id === x ? { ...old, checks } : old));
                  }
                });
              }}
            />
            {selection.notice}
            {v.checks.map((c, i) => (
              <fieldset key={i}>
                <legend>评审项 {i + 1}</legend>
                <Field
                  name={`检查代码 ${i + 1}`}
                  value={c.code}
                  onChange={(x) =>
                    set({
                      ...v,
                      checks: v.checks.map((r, n) =>
                        n === i ? { ...r, code: x } : r,
                      ),
                    })
                  }
                />
                <Toggle
                  name={`必需检查 ${i + 1}`}
                  value={c.required}
                  onChange={(x) =>
                    set({
                      ...v,
                      checks: v.checks.map((r, n) =>
                        n === i ? { ...r, required: x } : r,
                      ),
                    })
                  }
                />
                <Choice
                  name={`检查结论 ${i + 1}`}
                  value={c.decision}
                  choices={decisions}
                  onChange={(x) =>
                    set({
                      ...v,
                      checks: v.checks.map((r, n) =>
                        n === i
                          ? { ...r, decision: x as ReviewCheck["decision"] }
                          : r,
                      ),
                    })
                  }
                />
                <Field
                  name={`检查凭据 ${i + 1}`}
                  value={c.evidence}
                  onChange={(x) =>
                    set({
                      ...v,
                      checks: v.checks.map((r, n) =>
                        n === i ? { ...r, evidence: x } : r,
                      ),
                    })
                  }
                />
                <Field
                  name={`检查理由 ${i + 1}`}
                  value={c.reason}
                  onChange={(x) =>
                    set({
                      ...v,
                      checks: v.checks.map((r, n) =>
                        n === i ? { ...r, reason: x } : r,
                      ),
                    })
                  }
                />
                <button
                  type="button"
                  disabled={v.checks.length === 1}
                  onClick={() =>
                    set({ ...v, checks: v.checks.filter((_, n) => n !== i) })
                  }
                >
                  移除评审项 {i + 1}
                </button>
              </fieldset>
            ))}
            <button
              type="button"
              disabled={v.checks.length >= 100}
              onClick={() => set({ ...v, checks: [...v.checks, check()] })}
            >
              添加评审项
            </button>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "npi.issue")
    return (
      <CommandForm<Command<"npi.issue">>
        {...p}
        title="登记导入问题"
        save="保存导入问题"
        initial={() => ({
          action: "npi.issue",
          npi_id: selected(p, "npi"),
          phenomenon: "",
          risk: "",
          containment: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="npi"
              name="问题所属导入"
              value={v.npi_id}
              onChange={(x) => set({ ...v, npi_id: x })}
            />
            <Field
              name="问题现象"
              value={v.phenomenon}
              onChange={(x) => set({ ...v, phenomenon: x })}
            />
            <Field
              name="风险"
              value={v.risk}
              onChange={(x) => set({ ...v, risk: x })}
            />
            <Field
              name="遏制措施"
              value={v.containment}
              onChange={(x) => set({ ...v, containment: x })}
            />
          </>
        )}
      </CommandForm>
    );
  if (p.action === "npi.resolve")
    return (
      <CommandForm<Command<"npi.resolve">>
        {...p}
        title="验证或刷新问题解决依据"
        save="追加解决验证"
        initial={() => ({
          action: "npi.resolve",
          issue_id: selected(p, "npi_issue"),
          verified_cause: "",
          countermeasure: "",
          verification_evidence: "",
          test_ids: [],
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="npi_issue"
              name="待验证问题"
              value={v.issue_id}
              onChange={(x) => set({ ...v, issue_id: x })}
            />
            <Field
              name="已验证原因"
              value={v.verified_cause}
              onChange={(x) => set({ ...v, verified_cause: x })}
            />
            <Field
              name="对策"
              value={v.countermeasure}
              onChange={(x) => set({ ...v, countermeasure: x })}
            />
            <Field
              name="解决验证凭据"
              value={v.verification_evidence}
              onChange={(x) => set({ ...v, verification_evidence: x })}
            />
            <ManyObjects
              name="支持测试（可选）"
              items={p.items.test || []}
              value={v.test_ids}
              onChange={(x) => set({ ...v, test_ids: x })}
            />
            <p>
              可登记签署的过程检查证据。若引用测试，必须是当前有效的同一导入试做证据。新验证保留全部历史。
            </p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "npi.trial")
    return (
      <CommandForm<Command<"npi.trial">>
        {...p}
        title="登记导入试做证据"
        save="保存试做证据"
        initial={() => ({
          action: "npi.trial",
          npi_id: selected(p, "npi"),
          work_order_id: "",
          test_ids: [],
          evidence: "",
        })}
        canSubmit={(v) => v.test_ids.length > 0}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="npi"
              name="试做导入"
              value={v.npi_id}
              onChange={(x) => set({ ...v, npi_id: x })}
            />
            <Pick
              p={p}
              kind="work_order"
              name="试做工单"
              value={v.work_order_id}
              onChange={(x) => set({ ...v, work_order_id: x })}
            />
            <ManyObjects
              name="实际试做测试"
              items={p.items.test || []}
              value={v.test_ids}
              onChange={(x) => set({ ...v, test_ids: x })}
            />
            <Field
              name="试做凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
          </>
        )}
      </CommandForm>
    );
  if (p.action === "npi.approve")
    return (
      <CommandForm<Command<"npi.approve">>
        {...p}
        title="批准当前导入证据"
        save="提交导入批准"
        initial={() => ({
          action: "npi.approve",
          npi_id: selected(p, "npi"),
          evidence: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="npi"
              name="待批准导入"
              value={v.npi_id}
              onChange={(x) => set({ ...v, npi_id: x })}
            />
            <Field
              name="导入批准凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            <p>
              服务器核验当前检查、问题和试做资格。批准不代替客户批准或质量放行。
            </p>
          </>
        )}
      </CommandForm>
    );
  return null;
}
