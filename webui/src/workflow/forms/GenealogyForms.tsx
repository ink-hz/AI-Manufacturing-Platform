import type { OEMCommands, Origin } from "../types";
import { CommandForm, Field, Choice } from "./shared";
import { type OEMFormProps, Pick, selected, origins } from "./oemShared";
export function GenealogyForms(p: OEMFormProps) {
  if (p.action === "unit.alias")
    return (
      <CommandForm<Extract<OEMCommands, { action: "unit.alias" }>>
        {...p}
        title="登记客户序列号"
        save="追加客户序列号"
        initial={() => ({
          action: "unit.alias",
          unit_id: selected(p, "unit"),
          customer_serial: "",
          evidence: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="unit"
              name="对应出厂 SN"
              value={v.unit_id}
              onChange={(x) => set({ ...v, unit_id: x })}
            />
            <Field
              name="客户序列号"
              value={v.customer_serial}
              onChange={(x) => set({ ...v, customer_serial: x })}
            />
            <Field
              name="序列号对应凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            <p>客户身份来自当前项目，原出厂 SN 保持不变。</p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "component.install")
    return (
      <CommandForm<Extract<OEMCommands, { action: "component.install" }>>
        {...p}
        title="登记部件安装"
        save="保存部件安装"
        initial={() => ({
          action: "component.install",
          unit_id: selected(p, "unit"),
          material_id: "",
          component_serial: "",
          lot_id: null,
          origin: "manual",
          evidence: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="unit"
              name="安装产品 SN"
              value={v.unit_id}
              onChange={(x) => set({ ...v, unit_id: x })}
            />
            <Field
              name="部件物料业务编号"
              value={v.material_id}
              onChange={(x) => set({ ...v, material_id: x })}
            />
            <Field
              name="部件序列号"
              value={v.component_serial}
              onChange={(x) => set({ ...v, component_serial: x })}
            />
            <Pick
              p={p}
              kind="material_lot"
              name="部件批次（可选）"
              required={false}
              value={v.lot_id}
              onChange={(x) => set({ ...v, lot_id: x || null })}
            />
            <Choice
              name="部件来源"
              value={v.origin}
              choices={origins}
              onChange={(x) => set({ ...v, origin: x as Origin })}
            />
            <Field
              name="部件安装凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
          </>
        )}
      </CommandForm>
    );
  if (p.action === "component.remove")
    return (
      <CommandForm<Extract<OEMCommands, { action: "component.remove" }>>
        {...p}
        title="登记部件拆除"
        save="追加部件拆除"
        initial={() => ({
          action: "component.remove",
          component_link_id: selected(p, "component_link"),
          evidence: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="component_link"
              name="待拆除安装记录"
              value={v.component_link_id}
              onChange={(x) => set({ ...v, component_link_id: x })}
            />
            <Field
              name="部件拆除凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            <p>追加拆除事实，保留原安装时间、身份与证据。</p>
          </>
        )}
      </CommandForm>
    );
  return null;
}
