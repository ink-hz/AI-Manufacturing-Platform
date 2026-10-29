import type { OEMCommands, AssetContent, ObjectSummary } from "../types";
import { CommandForm, Field, Choice, ObjectChoice } from "./shared";
import {
  type OEMFormProps,
  Pick,
  Toggle,
  Names,
  decisions,
  selected,
} from "./oemShared";
const blank = (): AssetContent => ({
  title: "",
  category: "check",
  product_families: [""],
  execution_content: "",
  verification_method: "",
});
export function AssetFields({
  prefix,
  value: v,
  onChange: set,
}: {
  prefix: string;
  value: AssetContent;
  onChange(v: AssetContent): void;
}) {
  return (
    <fieldset>
      <legend>{prefix}</legend>
      <Field
        name={`${prefix}标题`}
        value={v.title}
        onChange={(x) => set({ ...v, title: x })}
      />
      <Choice
        name={`${prefix}类别`}
        value={v.category}
        choices={{
          check: "检查项",
          process_module: "过程模块",
          test_module: "测试模块",
        }}
        onChange={(x) => set({ ...v, category: x as AssetContent["category"] })}
      />
      <Names
        name={`${prefix}适用产品族`}
        value={v.product_families}
        onChange={(x) => set({ ...v, product_families: x })}
      />
      <Field
        name={`${prefix}执行内容`}
        value={v.execution_content}
        onChange={(x) => set({ ...v, execution_content: x })}
      />
      <Field
        name={`${prefix}验证方法`}
        value={v.verification_method}
        onChange={(x) => set({ ...v, verification_method: x })}
      />
    </fieldset>
  );
}
export function AssetForms(p: OEMFormProps) {
  if (p.action === "asset.publish")
    return (
      <CommandForm<Extract<OEMCommands, { action: "asset.publish" }>>
        {...p}
        title="发布可复用资产"
        save="发布固定资产修订"
        initial={() => ({
          action: "asset.publish",
          issue_id: selected(p, "npi_issue"),
          content: blank(),
          public_content: null,
          supersedes_id: null,
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="npi_issue"
              name="资产来源问题"
              value={v.issue_id}
              onChange={(x) => set({ ...v, issue_id: x })}
            />
            <Pick
              p={p}
              kind="reusable_asset"
              name="接续资产修订（可选）"
              value={v.supersedes_id}
              required={false}
              onChange={(x) => set({ ...v, supersedes_id: x || null })}
            />
            <AssetFields
              prefix="项目资产"
              value={v.content}
              onChange={(x) => set({ ...v, content: x })}
            />
            <p>默认仅本项目可见。发布要求来源问题具备当前有效验证。</p>
            {p.configurationAdmin && (
              <>
                <Toggle
                  name="单独编写并批准公共内容"
                  value={!!v.public_content}
                  onChange={(yes) =>
                    set({ ...v, public_content: yes ? blank() : null })
                  }
                />
                {v.public_content && (
                  <>
                    <p>
                      公共内容会向有工作区权限的用户公开，请独立编写通用内容。
                    </p>
                    <AssetFields
                      prefix="公共资产"
                      value={v.public_content}
                      onChange={(x) => set({ ...v, public_content: x })}
                    />
                  </>
                )}
              </>
            )}
          </>
        )}
      </CommandForm>
    );
  if (p.action === "asset.apply") {
    const local = p.items.reusable_asset || [];
    const foreign = (p.publicAssets || [])
      .filter((a) => !local.some((i) => i.id === a.asset_revision_id))
      .map(
        (a) =>
          ({
            id: a.asset_revision_id,
            kind: "reusable_asset",
            title: `公共 · ${a.content.title} · 修订 ${a.revision}`,
            state: "published",
            quantity: null,
            unit: null,
          }) as ObjectSummary,
      );
    return (
      <CommandForm<Extract<OEMCommands, { action: "asset.apply" }>>
        {...p}
        title="采用固定资产修订"
        save="登记资产采用"
        initial={() => ({
          action: "asset.apply",
          npi_id: selected(p, "npi"),
          asset_revision_id: "",
          required: true,
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="npi"
              name="采用目标导入"
              value={v.npi_id}
              onChange={(x) => set({ ...v, npi_id: x })}
            />
            <ObjectChoice
              name="采用资产修订"
              value={v.asset_revision_id}
              items={[...local, ...foreign]}
              onChange={(x) => set({ ...v, asset_revision_id: x })}
            />
            <Toggle
              name="作为必需检查"
              value={v.required}
              onChange={(x) => set({ ...v, required: x })}
            />
            <p>采用保存此修订的内容快照；仍须单独登记目标验证。</p>
          </>
        )}
      </CommandForm>
    );
  }
  if (p.action === "asset.verify")
    return (
      <CommandForm<Extract<OEMCommands, { action: "asset.verify" }>>
        {...p}
        title="验证已采用资产"
        save="追加资产验证"
        initial={() => ({
          action: "asset.verify",
          asset_use_id: selected(p, "asset_use"),
          decision: "blocked",
          evidence: "",
        })}
      >
        {(v, set) => (
          <>
            <Pick
              p={p}
              kind="asset_use"
              name="待验证采用"
              value={v.asset_use_id}
              onChange={(x) => set({ ...v, asset_use_id: x })}
            />
            <Choice
              name="资产验证结论"
              value={v.decision}
              choices={decisions}
              onChange={(x) => set({ ...v, decision: x as typeof v.decision })}
            />
            <Field
              name="资产验证凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
          </>
        )}
      </CommandForm>
    );
  return null;
}
