import { SystemPicker } from "./SystemPicker";
import type { Api } from "../api";
import { Choice } from "../projects/ui";
import { Field, Evidence } from "./ui";
import { assertions, packageKinds } from "./labels";
import type { PackageItem } from "./types";
export function PackageItemFields({
  current,
  api,
  updateItem,
}: {
  current: PackageItem;
  api: Api;
  updateItem: (patch: Partial<PackageItem>) => void;
}) {
  return (
    <>
      <Choice
        label="资料类别"
        value={current.kind}
        values={packageKinds}
        onChange={(v) => updateItem({ kind: v as PackageItem["kind"] })}
      />
      <Field
        label="资料名称"
        required
        maxLength={300}
        value={current.title}
        onChange={(v) => updateItem({ title: v })}
      />
      <Field
        label="来源名称"
        value={current.source_name}
        onChange={(v) => updateItem({ source_name: v })}
      />
      <Field
        label="来源编号或链接"
        value={current.source_ref}
        onChange={(v) => updateItem({ source_ref: v })}
      />
      <SystemPicker
        api={api}
        label="来源系统（可选）"
        value={current.source_system_id}
        onChange={(v) => updateItem({ source_system_id: v })}
      />
      <Field
        label="资料修订"
        value={current.revision}
        onChange={(v) => updateItem({ revision: v })}
      />
      <Field
        label="资料项负责人"
        value={current.owner}
        onChange={(v) => updateItem({ owner: v })}
      />
      <Choice
        label="资料核对结论"
        value={current.status}
        values={{
          pending: assertions.pending,
          verified: assertions.verified,
          na: assertions.na,
        }}
        onChange={(v) => updateItem({ status: v as PackageItem["status"] })}
      />
      <Field
        label="资料凭据"
        value={current.evidence}
        onChange={(v) => updateItem({ evidence: v })}
      />
      <Field
        label="资料核对理由"
        value={current.reason}
        onChange={(v) => updateItem({ reason: v })}
      />
      <p className="mf-full-width">
        来源：
        <Evidence value={current.source_ref} /> · 凭据：
        <Evidence value={current.evidence} />
      </p>
    </>
  );
}
