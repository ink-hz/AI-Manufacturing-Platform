import type { OEMCommands, Origin } from "../types";
import { CommandForm, Field, Choice } from "./shared";
import { type OEMFormProps, Pick, useSelected, origins } from "./oemShared";
import { Parameters } from "./EvidenceFields";
export function CalibrationForms(p: OEMFormProps) {
  const selection = useSelected(p);
  if (p.action === "calibration.record")
    return (
      <CommandForm<Extract<OEMCommands, { action: "calibration.record" }>>
        {...p}
        title="登记标定参数"
        save="保存待确认标定"
        initial={() => ({
          action: "calibration.record",
          run_id: "",
          algorithm_version: "",
          parameters: [{ name: "", value: "", unit: "" }],
          source_identity: "",
          source_version: "",
          origin: "manual",
          evidence: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="test_run"
              name="标定依据运行"
              value={v.run_id}
              onChange={(x) => {
                set({ ...v, run_id: x });
                void selection.read("test_run", x, (d) => {
                  if (d.value.kind === "test_run")
                    set((old) => ({
                      ...old,
                      origin:
                        d.value.kind === "test_run"
                          ? d.value.raw?.origin || "manual"
                          : old.origin,
                    }));
                });
              }}
            />
            {selection.notice}
            <Field
              name="标定算法版本"
              value={v.algorithm_version}
              onChange={(x) => set({ ...v, algorithm_version: x })}
            />
            <Parameters
              name="标定参数"
              value={v.parameters}
              onChange={(x) => set({ ...v, parameters: x })}
            />
            <Choice
              name="标定来源"
              value={v.origin}
              choices={origins}
              onChange={(x) => set({ ...v, origin: x as Origin })}
            />
            <Field
              name="参数来源标识"
              value={v.source_identity}
              onChange={(x) => set({ ...v, source_identity: x })}
            />
            <Field
              name="参数来源版本"
              value={v.source_version}
              onChange={(x) => set({ ...v, source_version: x })}
            />
            <Field
              name="参数登记凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            <p>保存后为待确认。此操作记录参数证据，不向设备写入。</p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "calibration.confirm")
    return (
      <CommandForm<Extract<OEMCommands, { action: "calibration.confirm" }>>
        {...p}
        title="登记独立读回确认"
        save="提交实际读回确认"
        initial={() => ({
          action: "calibration.confirm",
          calibration_id: "",
          readback: [],
          origin: "manual",
          source_identity: "",
          source_version: "",
          evidence: "",
        })}
        canSubmit={(v) =>
          !!v.calibration_id && v.readback.length > 0 && !selection.loading
        }
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="calibration"
              name="待确认标定"
              value={v.calibration_id}
              onChange={(x) => {
                set({ ...v, calibration_id: x, readback: [] });
                void selection.read("calibration", x, (d) => {
                  if (d.value.kind === "calibration") {
                    const value = d.value;
                    set((old) =>
                      old.calibration_id === x
                        ? {
                            ...old,
                            origin: value.origin,
                            readback: value.parameters.map((r) => ({
                              ...r,
                              value: "",
                            })),
                          }
                        : old,
                    );
                  }
                });
              }}
            />
            {selection.notice}
            {selection.detail?.value.kind === "calibration" && (
              <section aria-label="预期参数仅供核对">
                <h4>预期参数仅供核对</h4>
                {selection.detail.value.parameters.map((r) => (
                  <p key={r.name}>
                    {r.name} · {r.value} {r.unit}
                  </p>
                ))}
              </section>
            )}
            <Parameters
              name="实际读回"
              value={v.readback}
              lockedNames
              onChange={(x) => set({ ...v, readback: x })}
            />
            <p>
              来源：{origins[v.origin]}
              。请输入实际观察到的数值；确认不会执行设备读写。
            </p>
            <Field
              name="读回来源标识"
              value={v.source_identity}
              onChange={(x) => set({ ...v, source_identity: x })}
            />
            <Field
              name="读回来源版本"
              value={v.source_version}
              onChange={(x) => set({ ...v, source_version: x })}
            />
            <Field
              name="读回确认凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            <p>
              独立读回证据标识必须与原参数证据不同；允许同一有资格的操作者分别登记。
            </p>
          </>
        )}
      </CommandForm>
    );
  return null;
}
