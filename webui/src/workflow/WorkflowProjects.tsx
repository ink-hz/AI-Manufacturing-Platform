import { ConflictComparison } from "./ConflictComparison";
import { WorkflowError } from "./api";
import { useEffect, useRef, useState } from "react";
import type { MountOptions } from "../types";
import type { WorkflowApi } from "./api";
import type {
  ProjectCreate,
  ProjectDetail,
  WorkspaceProps,
  GrantChange,
} from "./types";
import { Field, Choice } from "./forms/shared";
export function WorkflowProjects({
  items,
  onOpen,
}: {
  items: ProjectDetail[];
  onOpen(p: ProjectDetail): void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>项目</th>
          <th>产线 / 产品</th>
          <th>客户</th>
          <th>原始承诺</th>
          <th>当前承诺</th>
        </tr>
      </thead>
      <tbody>
        {items.map((p) => (
          <tr key={p.id}>
            <td>
              <button onClick={() => onOpen(p)}>{p.name}</button>
            </td>
            <td>
              {p.line_id} / {p.product}
            </td>
            <td>{p.customer_id}</td>
            <td>
              {p.summary.original_order_quantity} {p.unit.code}
            </td>
            <td>
              {p.summary.current_order_quantity} {p.unit.code}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
export function ProjectForm({
  readOnly,
  api,
  onSaved,
  onDirty,
}: {
  readOnly: boolean;
  api: WorkflowApi;
  onSaved(p: ProjectDetail): void;
  onDirty(k: string, d: boolean): void;
}) {
  const [v, setV] = useState<ProjectCreate>(() => ({
      operation_id: crypto.randomUUID(),
      name: "",
      line_id: "",
      product: "",
      customer_id: "",
      mode: "internal",
      unit: { code: "件", scale: 0 },
      quantity: "",
      contract: {
        customer_approval_required: "unknown",
        customer_release_required: "unknown",
        acceptance_required: "unknown",
        customer_revision: "",
        internal_revision: "",
        material_ownership_rules: "",
      },
    })),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      onDirty("create-project", false);
    };
  }, []);
  function set(value: ProjectCreate) {
    setV({ ...value, operation_id: crypto.randomUUID() });
    onDirty("create-project", true);
  }
  return (
    <form
      className="wf-form"
      aria-label="新建制造项目"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy || readOnly) return;
        setBusy(true);
        try {
          const p = await api.createProject(v);
          if (alive.current) {
            onDirty("create-project", false);
            onSaved(p);
          }
        } catch (e) {
          if (alive.current) setError(String(e));
        } finally {
          if (alive.current) setBusy(false);
        }
      }}
    >
      <h2>新建制造项目</h2>
      <fieldset disabled={busy || readOnly}>
        {(
          ["name", "line_id", "product", "customer_id", "quantity"] as const
        ).map((k, i) => (
          <Field
            key={k}
            name={
              ["项目名称", "产线名称", "项目产品", "项目客户", "项目目标数量"][
                i
              ]
            }
            value={v[k]}
            onChange={(x) => set({ ...v, [k]: x })}
          />
        ))}
        <Choice
          name="项目模式"
          value={v.mode}
          choices={{ internal: "自研", oem: "代工" }}
          onChange={(x) => set({ ...v, mode: x as typeof v.mode })}
        />
        <Field
          name="项目单位"
          value={v.unit.code}
          onChange={(x) => set({ ...v, unit: { ...v.unit, code: x } })}
        />
        <Choice
          name="数量小数位"
          value={String(v.unit.scale)}
          choices={Object.fromEntries(
            [0, 1, 2, 3, 4, 5, 6].map((n) => [String(n), String(n)]),
          )}
          onChange={(x) => set({ ...v, unit: { ...v.unit, scale: Number(x) } })}
        />
        {(
          [
            "customer_approval_required",
            "customer_release_required",
            "acceptance_required",
          ] as const
        ).map((k, i) => (
          <Choice
            key={k}
            name={
              ["合同要求客户批准", "合同要求客户放行", "合同要求客户验收"][i]
            }
            value={String(v.contract[k])}
            choices={{ unknown: "待确认", true: "要求", false: "不要求" }}
            onChange={(x) =>
              set({
                ...v,
                contract: {
                  ...v.contract,
                  [k]: x === "unknown" ? "unknown" : x === "true",
                },
              })
            }
          />
        ))}
        {(
          [
            "customer_revision",
            "internal_revision",
            "material_ownership_rules",
          ] as const
        ).map((k, i) => (
          <Field
            key={k}
            name={["合同客户版本", "合同内部版本", "物料权属规则"][i]}
            value={v.contract[k]}
            onChange={(x) => set({ ...v, contract: { ...v.contract, [k]: x } })}
          />
        ))}
      </fieldset>
      {error && <p role="alert">{error}</p>}
      <button disabled={busy || readOnly}>创建制造项目</button>
    </form>
  );
}
export function MemberPicker({
  findSubjects,
  value,
  onChange,
}: {
  findSubjects: NonNullable<MountOptions["findSubjects"]>;
  value: string;
  onChange(id: string): void;
}) {
  const [query, setQuery] = useState(""),
    [items, setItems] = useState<{ id: string; displayName: string }[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const c = new AbortController();
    setError("");
    findSubjects(query, c.signal)
      .then((v) => {
        if (active) setItems(v);
      })
      .catch((e) => {
        if (active && e.name !== "AbortError")
          setError("无法读取可授权账号，请重试。");
      });
    return () => {
      active = false;
      c.abort();
    };
  }, [findSubjects, query]);
  return (
    <>
      <Field
        name="查找成员姓名"
        required={false}
        value={query}
        onChange={setQuery}
      />
      <Choice
        name="授权成员"
        value={value}
        choices={{
          "": "请选择活跃账号",
          ...Object.fromEntries(items.map((u) => [u.id, u.displayName])),
        }}
        onChange={onChange}
      />
      {error && <p role="alert">{error}</p>}
    </>
  );
}
export function Members(
  p: WorkspaceProps & { findSubjects?: MountOptions["findSubjects"] },
) {
  const [loadedUser, setLoadedUser] = useState(""),
    [user, setUser] = useState(""),
    [v, setV] = useState<GrantChange>(() => ({
      operation_id: crypto.randomUUID(),
      expected_version: p.project.version,
      scope: { kind: "project", project_id: p.project.id },
      roles: [],
      qualifications: [],
      active: true,
      evidence: "",
    })),
    [error, setError] = useState(""),
    [conflict, setConflict] = useState<WorkflowError | null>(null),
    [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      p.onDirty("members", false);
    };
  }, [p.project.id]);
  useEffect(() => {
    let active = true;
    setLoadedUser("");
    setError("");
    if (user) p.api.member(p.project.id, user).then(r => {
      if (!active) return;
      const old = r.items.find(m => m.user_id === user);
      setV(v => ({...v, operation_id: crypto.randomUUID(), roles: old?.roles || [], qualifications: old?.qualifications || [], active: old?.active ?? true}));
      setLoadedUser(user);
    }).catch(e => { if (active) setError("无法读取所选成员授权，请重新选择后重试。" + String(e)); });
    return () => { active = false; };
  }, [p.api, p.project.id, user]);
  const memberReady = !!user && loadedUser === user;
  function set(value: GrantChange) {
    setConflict(null);
    setV({ ...value, operation_id: crypto.randomUUID() });
    p.onDirty("members", true);
  }
  const roles = {
      project_owner: "项目负责人",
      engineering: "工程",
      planner: "计划",
      supply: "供应",
      production: "生产",
      quality: "质量",
      warehouse: "仓储",
    },
    quals = {
      inspection: "检验资格",
      disposition: "处置资格",
      quality_release: "质量放行资格",
      readiness_verification: "准备依据核验资格",
    };
  return (
    <section>
      <h3>项目成员授权</h3>
      <p>
        按真实账号配置项目职责与资格，所有变更需凭据；不会自动授予质量或准备核验资格。
      </p>
      {!p.findSubjects ? (
        <p>当前宿主未提供账号目录，暂不能编辑成员授权。</p>
      ) : (
        <form
          className="wf-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy || p.readOnly || !memberReady) return;
            setBusy(true);
            try {
              const result = await p.api.grant(p.project.id, user, v);
              if (alive.current) {
                p.onDirty("members", false);
                p.onChanged(result);
              }
            } catch (e) {
              if (alive.current) {
                setError(String(e));
                setConflict(
                  e instanceof WorkflowError && e.status === 409 ? e : null,
                );
              }
            } finally {
              if (alive.current) setBusy(false);
            }
          }}
        >
          <fieldset disabled={busy || p.readOnly}>
            <MemberPicker
              findSubjects={p.findSubjects}
              value={user}
              onChange={(id) => {
                setUser(id);
                setLoadedUser("");
                setConflict(null);
              }}
            />
            <fieldset disabled={!memberReady}>
            {(["roles", "qualifications"] as const).map((k) => (
              <fieldset key={k}>
                <legend>{k === "roles" ? "职责" : "资格"}</legend>
                {Object.entries(k === "roles" ? roles : quals).map(
                  ([key, name]) => (
                    <label key={key}>
                      <input
                        type="checkbox"
                        aria-label={name}
                        checked={v[k].includes(key)}
                        onChange={(e) =>
                          set({
                            ...v,
                            [k]: e.target.checked
                              ? [...v[k], key]
                              : v[k].filter((x) => x !== key),
                          })
                        }
                      />
                      {name}
                    </label>
                  ),
                )}
              </fieldset>
            ))}
            <Choice
              name="授权状态"
              value={String(v.active)}
              choices={{ true: "启用", false: "撤销" }}
              onChange={(x) => set({ ...v, active: x === "true" })}
            />
            <Field
              name="授权凭据"
              value={v.evidence}
              onChange={(x) => set({ ...v, evidence: x })}
            />
            </fieldset>
          </fieldset>
          {conflict && (
            <ConflictComparison
              api={p.api}
              projectId={p.project.id}
              version={v.expected_version}
              error={conflict}
              memberId={user}
            />
          )}
          <button disabled={busy || p.readOnly || !memberReady}>保存成员授权</button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
