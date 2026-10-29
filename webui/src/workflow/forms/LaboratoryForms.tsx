import type { OEMCommands, Measurement } from "../types";
import { CommandForm, Field, Choice, SourceFields, source } from "./shared";
import { type OEMFormProps, Pick, selected, useSelected } from "./oemShared";
import { Measurements, RawFields } from "./EvidenceFields";
export function LaboratoryForms(p: OEMFormProps) {
  const selection = useSelected(p);
  if (p.action === "test_plan.publish")
    return (
      <CommandForm<Extract<OEMCommands, { action: "test_plan.publish" }>>
        {...p}
        title="发布测试计划"
        save="发布固定测试计划"
        initial={() => ({
          action: "test_plan.publish",
          revision_id: selected(p, "revision"),
          level: "",
          station: "",
          equipment: "",
          fixture: "",
          algorithm_version: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="revision"
              name="测试计划固定修订"
              value={v.revision_id}
              onChange={(x) => set({ ...v, revision_id: x })}
            />
            {(
              [
                ["level", "测试层级"],
                ["station", "测试工位"],
                ["equipment", "测试设备"],
                ["fixture", "测试治具"],
                ["algorithm_version", "算法版本"],
              ] as const
            ).map(([key, name]) => (
              <Field
                key={key}
                name={name}
                value={v[key]}
                onChange={(x) => set({ ...v, [key]: x })}
              />
            ))}
            <p>
              固化已有修订的测试规范、程序、限值和固件，不执行算法或连接设备。
            </p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "test_run.start")
    return (
      <CommandForm<Extract<OEMCommands, { action: "test_run.start" }>>
        {...p}
        title="开始测试运行"
        save="登记运行开始"
        initial={() => ({
          action: "test_run.start",
          plan_id: selected(p, "test_plan"),
          unit_id: selected(p, "unit"),
          rework_order_id: null,
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="test_plan"
              name="运行测试计划"
              value={v.plan_id}
              onChange={(x) => set({ ...v, plan_id: x })}
            />
            <Pick
              p={p}
              kind="unit"
              name="运行产品 SN"
              value={v.unit_id}
              onChange={(x) => set({ ...v, unit_id: x })}
            />
            <Pick
              p={p}
              kind="rework"
              name="返工单（可选）"
              value={v.rework_order_id}
              required={false}
              onChange={(x) => set({ ...v, rework_order_id: x || null })}
            />
            <p>核验实际开工与执行范围；登记开始不代表测试通过。</p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "test_run.finish")
    return (
      <CommandForm<Extract<OEMCommands, { action: "test_run.finish" }>>
        {...p}
        title="登记测试运行结果"
        save="保存运行结果"
        initial={() => ({
          action: "test_run.finish",
          run_id: "",
          state: "completed",
          source: source("test"),
          measurements: [],
          raw: { origin: "manual", curves: [], logs: [] },
          reason: null,
        })}
        canSubmit={(v) =>
          !!v.run_id &&
          !selection.loading &&
          (v.state !== "completed" || v.measurements.length > 0)
        }
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="test_run"
              name="待结束运行"
              value={v.run_id}
              onChange={(x) => {
                set({ ...v, run_id: x, measurements: [] });
                void selection.read("test_run", x, (run) => {
                  if (run.value.kind === "test_run")
                    void selection.read(
                      "test_plan",
                      run.value.plan_id,
                      (plan) => {
                        if (plan.value.kind === "test_plan") {
                          const measurements: Measurement[] =
                            plan.value.test_spec.measurements.map((m) => ({
                              ...m,
                              value: "",
                            }));
                          set((old) =>
                            old.run_id === x
                              ? {
                                  ...old,
                                  measurements:
                                    old.state === "completed"
                                      ? measurements
                                      : [],
                                }
                              : old,
                          );
                        }
                      },
                    );
                });
              }}
            />
            {selection.notice}
            <Choice
              name="运行结束状态"
              value={v.state}
              choices={{
                completed: "完成（按实测值判定）",
                aborted: "中断",
                invalid: "无效",
              }}
              onChange={(x) => {
                const state = x as typeof v.state;
                const plan = selection.detail?.value;
                set({
                  ...v,
                  state,
                  measurements:
                    state === "completed" && plan?.kind === "test_plan"
                      ? plan.test_spec.measurements.map((m) => ({
                          ...m,
                          value: "",
                        }))
                      : [],
                  reason: state === "completed" ? null : "",
                });
              }}
            />
            {v.state === "completed" ? (
              <Measurements
                value={v.measurements}
                onChange={(x) => set({ ...v, measurements: x })}
              />
            ) : (
              <Field
                name="中断或无效原因"
                value={v.reason || ""}
                onChange={(x) => set({ ...v, reason: x })}
              />
            )}
            <RawFields value={v.raw} onChange={(x) => set({ ...v, raw: x })} />
            <SourceFields
              value={v.source}
              onChange={(x) => set({ ...v, source: x })}
            />
            <p>只有有检验资格的账号可登记结果。质量与客户放行仍需独立办理。</p>
          </>
        )}
      </CommandForm>
    );
  return null;
}
