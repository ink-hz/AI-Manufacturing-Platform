import { useEffect, useRef, useState } from "react";
import type { Api } from "../api";
import type { Catalog } from "../types";
import type {
  ProjectDetailData,
  ProjectSummary,
  ProjectFields,
  ProjectCreate,
} from "./types";
import { message } from "./types";
import { useDirty, SaveError, Choice, type DirtyChange } from "./ui";
export function ProjectForm({
  api,
  catalog,
  project,
  readOnly,
  onDirty,
  onSaved,
  onCancel,
  onReload,
}: {
  api: Api;
  catalog: Catalog;
  project?: ProjectSummary;
  readOnly: boolean;
  onDirty: DirtyChange;
  onSaved: (d: ProjectDetailData) => void;
  onCancel: () => void;
  onReload?: () => void;
}) {
  const baselineVersion = useRef(project?.version);
  const initial = useRef<ProjectFields>({
    name: project?.name || "",
    owner: project?.owner || "",
    product: project?.product || "",
    customer: project?.customer || "",
    due_date: project?.due_date || null,
    target_quantity: project?.target_quantity || null,
    summary: project?.summary || "",
  }).current;
  const [value, setValue] = useState(initial),
    [line, setLine] = useState(
      project?.line_id ||
        catalog.lines.find((l) => l.enabled && l.group_id === "internal")?.id ||
        catalog.lines.find((l) => l.enabled)?.id ||
        "",
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const operation = useRef<ProjectCreate | null>(null),
    lock = useRef(false);
  const [frozen, setFrozen] = useState(false);
  const dirty =
    JSON.stringify(initial) !== JSON.stringify(value) ||
    (!project &&
      !!line &&
      line !==
        (catalog.lines.find((l) => l.enabled && l.group_id === "internal")
          ?.id || catalog.lines.find((l) => l.enabled)?.id)) ||
    !!operation.current;
  useDirty("project-form", dirty || busy, onDirty);
  function update<K extends keyof ProjectFields>(key: K, v: ProjectFields[K]) {
    setValue({ ...value, [key]: v });
  }
  async function save() {
    if (lock.current || readOnly) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      let result: ProjectDetailData;
      if (project)
        result = await api.updateProject(project.id, {
          ...value,
          expected_version: baselineVersion.current!,
        });
      else {
        operation.current ??= {
          ...value,
          line_id: line,
          operation_id: crypto.randomUUID(),
        };
        setFrozen(true);
        result = await api.createProject(operation.current);
      }
      operation.current = null;
      if (active.current) onSaved(result);
    } catch (e) {
      if (active.current) setError(message(e));
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  }
  const disabled = readOnly || busy || frozen;
  return (
    <section className="mf-surface mf-editor">
      <div className="mf-section-heading">
        <div>
          <h2>{project ? "编辑项目资料" : "新建制造项目"}</h2>
          <p className="mf-muted">
            项目事实独立保存，不会自动复制流程参考中的现状。
          </p>
        </div>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <fieldset disabled={disabled} className="mf-form-grid">
          <label className="mf-field">
            项目名称 *
            <input
              aria-label="项目名称"
              required
              maxLength={200}
              value={value.name}
              onChange={(e) => update("name", e.target.value)}
            />
          </label>
          {!project && (
            <Choice
              label="业务线"
              value={line}
              values={Object.fromEntries(
                catalog.lines
                  .filter(
                    (l) =>
                      l.enabled &&
                      catalog.groups.some(
                        (g) => g.id === l.group_id && g.enabled,
                      ),
                  )
                  .map((l) => [l.id, l.name]),
              )}
              onChange={setLine}
            />
          )}
          <label className="mf-field">
            项目负责人 *
            <input
              aria-label="项目负责人"
              required
              maxLength={200}
              value={value.owner}
              onChange={(e) => update("owner", e.target.value)}
            />
          </label>
          <label className="mf-field">
            产品 / 型号
            <input
              aria-label="产品型号"
              maxLength={200}
              value={value.product}
              onChange={(e) => update("product", e.target.value)}
            />
          </label>
          <label className="mf-field">
            {catalog.lines.find((l) => l.id === line)?.group_id === "internal"
              ? "接收方"
              : "委托客户"}
            <input
              aria-label="客户或接收方"
              maxLength={200}
              value={value.customer}
              onChange={(e) => update("customer", e.target.value)}
            />
          </label>
          <label className="mf-field">
            目标交期
            <input
              aria-label="目标交期"
              type="date"
              value={value.due_date || ""}
              onChange={(e) => update("due_date", e.target.value || null)}
            />
          </label>
          <label className="mf-field">
            计划数量
            <input
              aria-label="计划数量"
              type="number"
              min={1}
              max={1000000000}
              step={1}
              value={value.target_quantity ?? ""}
              onChange={(e) =>
                update(
                  "target_quantity",
                  e.target.value ? Number(e.target.value) : null,
                )
              }
            />
          </label>
          <label className="mf-field mf-full-width">
            项目说明
            <textarea
              aria-label="项目说明"
              maxLength={6000}
              rows={3}
              value={value.summary}
              onChange={(e) => update("summary", e.target.value)}
            />
          </label>
        </fieldset>
        {error && (
          <SaveError
            error={error}
            onKeep={() => setError("")}
            onReload={onReload}
          />
        )}
        {frozen && (
          <p className="mf-muted">
            本次创建内容已锁定，重试将使用同一操作标识。需要修改时请取消本次创建。
          </p>
        )}
        <div className="mf-actions">
          <button
            className="mf-primary"
            disabled={
              busy ||
              readOnly ||
              !line ||
              !value.name.trim() ||
              !value.owner.trim()
            }
            type="submit"
          >
            {busy ? "正在保存…" : project ? "保存项目" : "创建项目"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              operation.current = null;
              onCancel();
            }}
          >
            {frozen ? "取消本次创建" : "取消"}
          </button>
        </div>
      </form>
    </section>
  );
}
