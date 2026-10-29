import type { OEMCommands, ObjectKind, Origin } from "../types";
import { CommandForm, Field, Choice } from "./shared";
import { type OEMFormProps, Pick, origins, selected } from "./oemShared";
import { label } from "../labels";
export const authorityCategories: ObjectKind[] = [
  "demand",
  "order_line",
  "commitment_change",
  "revision",
  "work_order",
  "plan",
  "requirement",
  "commitment",
  "material_lot",
  "receipt",
  "reservation",
  "exchange",
  "unit",
  "interruption",
  "test",
  "nonconformance",
  "rework",
  "release",
  "eco",
  "shipment",
  "closure",
  "rma",
  "capa",
  "npi",
  "npi_issue",
  "reusable_asset",
  "asset_use",
  "test_plan",
  "test_run",
  "calibration",
  "component_link",
  "authority_rule",
  "arrival",
];
export function AuthorityForms(p: OEMFormProps) {
  if (p.action === "authority.register")
    return (
      <CommandForm<Extract<OEMCommands, { action: "authority.register" }>>
        {...p}
        title="登记系统责任映射"
        save="保存责任映射"
        initial={() => ({
          action: "authority.register",
          object_category: "receipt",
          business_scope: "",
          system: "",
          responsible_identity: "",
          evidence: "",
          origin: "manual",
        })}
      >
        {(v, set) => (
          <>
            <Choice
              name="责任对象类别"
              value={v.object_category}
              choices={Object.fromEntries(
                authorityCategories.map((k) => [k, label(k)]),
              )}
              onChange={(x) => set({ ...v, object_category: x as ObjectKind })}
            />
            <Field
              name="责任业务范围"
              value={v.business_scope}
              onChange={(x) => set({ ...v, business_scope: x })}
            />
            <Field
              name="候选责任系统"
              value={v.system}
              onChange={(x) => set({ ...v, system: x })}
            />
            <Field
              name="责任人或组织"
              value={v.responsible_identity}
              onChange={(x) => set({ ...v, responsible_identity: x })}
            />
            <Field
              name="责任登记凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            <Choice
              name="责任映射来源"
              value={v.origin}
              choices={origins}
              onChange={(x) => set({ ...v, origin: x as Origin })}
            />
            <p>
              登记责任与契约范围；不会连接系统或切换生产路由。重复范围生成下一修订。
            </p>
          </>
        )}
      </CommandForm>
    );
  if (p.action === "authority.verify")
    return (
      <CommandForm<Extract<OEMCommands, { action: "authority.verify" }>>
        {...p}
        title="核验责任契约"
        save="保存契约核验"
        initial={() => ({
          action: "authority.verify",
          rule_id: selected(p, "authority_rule"),
          contract_evidence: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="authority_rule"
              name="待核验责任映射"
              value={v.rule_id}
              onChange={(x) => set({ ...v, rule_id: x })}
            />
            <Field
              name="责任契约核验凭据"
              value={v.contract_evidence}
              onChange={(x) => set({ ...v, contract_evidence: x })}
            />
            <p>核验仅确认责任契约依据，连接状态由服务器独立提供。</p>
          </>
        )}
      </CommandForm>
    );
  return null;
}
