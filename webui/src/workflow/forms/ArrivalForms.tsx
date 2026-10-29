import type { OEMCommands } from "../types";
import { CommandForm, Field, SourceFields, source } from "./shared";
import { type OEMFormProps, Pick, useSelected } from "./oemShared";
export function ArrivalForms(p: OEMFormProps) {
  const selection = useSelected(p);
  if (p.action === "arrival.record")
    return (
      <CommandForm<Extract<OEMCommands, { action: "arrival.record" }>>
        {...p}
        title="登记收货观察"
        save="保存收货观察"
        initial={() => ({
          action: "arrival.record",
          arrival_number: "",
          location: "",
          package_count: 1,
          description: "",
          source: source("arrival"),
        })}
        canSubmit={(v) =>
          Number.isInteger(v.package_count) &&
          v.package_count >= 1 &&
          v.package_count <= 100000
        }
      >
        {(v, set) => (
          <>
            <Field
              name="到件编号（扫码或输入）"
              value={v.arrival_number}
              onChange={(x) => set({ ...v, arrival_number: x })}
            />
            <Field
              name="观察收货或暂存位置"
              value={v.location}
              onChange={(x) => set({ ...v, location: x })}
            />
            <Field
              name="观察包裹数"
              type="number"
              value={String(v.package_count)}
              onChange={(x) => set({ ...v, package_count: Number(x) })}
            />
            <Field
              name="实物观察描述"
              value={v.description}
              onChange={(x) => set({ ...v, description: x })}
            />
            <SourceFields
              value={v.source}
              onChange={(x) => set({ ...v, source: x })}
            />
            <p>
              支持扫描枪输入已见标签；尚未确认的采购、物料与寄件身份保持未知。观察位置不是库存移动记录。
            </p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "arrival.match")
    return (
      <CommandForm<Extract<OEMCommands, { action: "arrival.match" }>>
        {...p}
        title="匹配或纠正收货凭据"
        save="追加收货匹配"
        initial={() => ({
          action: "arrival.match",
          arrival_id: "",
          receipt_id: "",
          evidence: "",
          correction_reason: null,
        })}
        canSubmit={(v) =>
          !!v.arrival_id &&
          !!v.receipt_id &&
          !selection.loading &&
          selection.detail?.value.kind === "arrival" &&
          selection.detail.value.receipt_id !== v.receipt_id
        }
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="arrival"
              name="待匹配收货观察"
              value={v.arrival_id}
              onChange={(x) => {
                set({
                  ...v,
                  arrival_id: x,
                  receipt_id: "",
                  correction_reason: null,
                });
                void selection.read("arrival", x, (d) => {
                  if (d.value.kind === "arrival")
                    set((old) =>
                      old.arrival_id === x
                        ? {
                            ...old,
                            correction_reason:
                              d.value.kind === "arrival" && d.value.receipt_id
                                ? ""
                                : null,
                          }
                        : old,
                    );
                });
              }}
            />
            {selection.notice}
            <Pick
              p={p}
              kind="receipt"
              name="核对后的到货凭据"
              value={v.receipt_id}
              onChange={(x) => set({ ...v, receipt_id: x })}
            />
            <Field
              name="收货匹配凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            {v.correction_reason !== null && (
              <Field
                name="匹配纠正原因"
                value={v.correction_reason}
                onChange={(x) => set({ ...v, correction_reason: x })}
              />
            )}
            <p>
              核对实际同项目到货凭据后登记。纠正保留原匹配历史，不代表来料检验或库存预留。
            </p>
          </>
        )}
      </CommandForm>
    );
  return null;
}
