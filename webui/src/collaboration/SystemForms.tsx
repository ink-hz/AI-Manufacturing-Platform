import { useState } from "react";
import type { Api } from "../api";
import type { Catalog } from "../types";
import { Choice } from "../projects/ui";
import type {
  SystemRecord,
  SystemFields,
  Authority,
  AuthorityFields,
} from "./types";
import { Field, Note, MutationForm, type EditorHost } from "./ui";
import { methods, objects, usages } from "./labels";
const systemFields = (s?: SystemRecord, line = ""): SystemFields => ({
  name: s?.name || "",
  kind: s?.kind || "",
  line_ids: s?.line_ids || [line],
  business_owner: s?.business_owner || "",
  it_owner: s?.it_owner || "",
  usage: s?.usage || "unverified",
  method: s?.method || "unknown",
  notes: s?.notes || "",
  active: s?.active ?? true,
});
export function SystemForm({
  api,
  catalog,
  system,
  ...host
}: { api: Api; catalog: Catalog; system?: SystemRecord } & EditorHost) {
  const [initial] = useState(() => systemFields(system, catalog.lines[0]?.id));
  const [d, set] = useState(initial);
  const update = <K extends keyof SystemFields>(k: K, v: SystemFields[K]) =>
    set({ ...d, [k]: v });
  return (
    <>
      <h3>{system ? "系统详情" : "登记系统"}</h3>
      <MutationForm
        {...host}
        draft={d}
        initial={initial}
        version={system?.version}
        label="保存系统"
        write={(body) =>
          system ? api.updateSystem(system.id, body) : api.createSystem(body)
        }
      >
        <Field
          label="系统名称"
          value={d.name}
          onChange={(v) => update("name", v)}
          required
          maxLength={300}
        />
        <Field
          label="系统类别"
          value={d.kind}
          onChange={(v) => update("kind", v)}
          required
          maxLength={300}
        />
        <div className="mf-field mf-full-width">
          <span>覆盖业务线 *</span>
          <div className="mf-checks">
            {catalog.lines.map((l) => (
              <label key={l.id}>
                <input
                  type="checkbox"
                  checked={d.line_ids.includes(l.id)}
                  onChange={(e) =>
                    update(
                      "line_ids",
                      e.target.checked
                        ? [...d.line_ids, l.id]
                        : d.line_ids.filter((id) => id !== l.id),
                    )
                  }
                />
                {l.name}
              </label>
            ))}
          </div>
        </div>
        <Field
          label="业务负责人"
          value={d.business_owner}
          onChange={(v) => update("business_owner", v)}
        />
        <Field
          label="IT负责人"
          value={d.it_owner}
          onChange={(v) => update("it_owner", v)}
        />
        <Choice
          label="使用现状"
          values={usages}
          value={d.usage}
          onChange={(v) => update("usage", v as SystemFields["usage"])}
        />
        <Choice
          label="协同方式"
          values={methods}
          value={d.method}
          onChange={(v) => update("method", v as SystemFields["method"])}
        />
        <Note
          label="现状说明"
          value={d.notes}
          onChange={(v) => update("notes", v)}
        />
        <label>
          <input
            type="checkbox"
            checked={d.active}
            onChange={(e) => update("active", e.target.checked)}
          />
          有效记录
        </label>
        {system && (
          <button type="button" onClick={() => update("active", false)}>
            停用系统
          </button>
        )}
      </MutationForm>
    </>
  );
}
export function AuthorityForm({
  api,
  catalog,
  systems,
  authority,
  ...host
}: {
  api: Api;
  catalog: Catalog;
  systems: SystemRecord[];
  authority?: Authority;
} & EditorHost) {
  const [initial] = useState<AuthorityFields>(() => ({
    line_id: authority?.line_id || catalog.lines[0]?.id,
    object_type: authority?.object_type || "material",
    system_id:
      authority?.system_id ||
      systems.find((s) => s.active && s.line_ids.includes(catalog.lines[0]?.id))
        ?.id ||
      "",
    entry_point: authority?.entry_point || "",
    owner: authority?.owner || "",
    notes: authority?.notes || "",
    active: authority?.active ?? true,
  }));
  const [d, set] = useState(initial);
  const update = <K extends keyof AuthorityFields>(
    k: K,
    v: AuthorityFields[K],
  ) => set({ ...d, [k]: v });
  return (
    <>
      <h3>责任入口约定</h3>
      <MutationForm
        {...host}
        draft={d}
        initial={initial}
        version={authority?.version}
        label="保存责任约定"
        write={(body) =>
          authority
            ? api.updateAuthority(authority.id, body)
            : api.createAuthority(body)
        }
      >
        <Choice
          label="责任业务线"
          value={d.line_id}
          values={Object.fromEntries(catalog.lines.map((l) => [l.id, l.name]))}
          onChange={(line) =>
            set({
              ...d,
              line_id: line,
              system_id:
                systems.find((s) => s.active && s.line_ids.includes(line))
                  ?.id || "",
            })
          }
        />
        <Choice
          label="业务对象"
          value={d.object_type}
          values={objects}
          onChange={(v) =>
            update("object_type", v as AuthorityFields["object_type"])
          }
        />
        <Choice
          label="责任系统"
          value={d.system_id}
          values={{
            "": "请选择",
            ...Object.fromEntries(
              systems
                .filter((s) => s.active && s.line_ids.includes(d.line_id))
                .map((s) => [s.id, s.name]),
            ),
          }}
          onChange={(v) => update("system_id", v)}
        />
        <Field
          label="录入入口"
          value={d.entry_point}
          onChange={(v) => update("entry_point", v)}
          required
          maxLength={300}
        />
        <Field
          label="责任人"
          value={d.owner}
          onChange={(v) => update("owner", v)}
          required
          maxLength={300}
        />
        <Note
          label="责任说明"
          value={d.notes}
          onChange={(v) => update("notes", v)}
        />
        <label>
          <input
            type="checkbox"
            checked={d.active}
            onChange={(e) => update("active", e.target.checked)}
          />
          有效约定
        </label>
      </MutationForm>
    </>
  );
}
