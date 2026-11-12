import { ConflictComparison } from "../ConflictComparison";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  CommandFields,
  SourceRef,
  WorkspaceProps,
  WorkflowCommand,
  ObjectSummary,
} from "../types";
import { WorkflowError } from "../api";
import { label, objectTitle } from "../labels";
export { label, objectTitle } from "../labels";
export function Field({
  name,
  value,
  onChange,
  type = "text",
  required = true,
}: {
  name: string;
  value: string;
  onChange(v: string): void;
  type?: string;
  required?: boolean;
}) {
  return (
    <label>
      {name}
      <input
        aria-label={name}
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
export function Choice({
  name,
  value,
  onChange,
  choices,
  required = true,
}: {
  name: string;
  value: string;
  onChange(v: string): void;
  choices: Record<string, string>;
  required?: boolean;
}) {
  return (
    <label>
      {name}
      <select
        aria-label={name}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {Object.entries(choices).map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}
export function ObjectChoice({
  name,
  value,
  onChange,
  items,
  required = true,
}: {
  name: string;
  value: string;
  onChange(v: string): void;
  items: ObjectSummary[];
  required?: boolean;
}) {
  return (
    <Choice
      required={required}
      name={name}
      value={value}
      onChange={onChange}
      choices={{
        "": "请选择",
        ...Object.fromEntries(
          items.map((i) => [
            i.id,
            `${objectTitle(i)} · ${label(i.state)}${i.quantity !== null ? " · " + i.quantity + " " + i.unit : ""}`,
          ]),
        ),
      }}
    />
  );
}
export const source = (object_type: string): SourceRef => ({
  system: "人工登记",
  object_type,
  external_id: "",
  version: 1,
  mode: "manual",
  occurred_at: "",
  collected_at: "",
  cutoff: null,
  evidence: "",
});
export function SourceFields({
  value,
  onChange,
}: {
  value: SourceRef;
  onChange(v: SourceRef): void;
}) {
  return (
    <fieldset>
      <legend>来源依据 · 人工登记</legend>
      <Field
        name="来源系统"
        value={value.system}
        onChange={(v) => onChange({ ...value, system: v })}
      />
      <Field
        name="来源业务编号"
        value={value.external_id}
        onChange={(v) => onChange({ ...value, external_id: v })}
      />
      <Field
        name="来源版本"
        type="number"
        value={String(value.version)}
        onChange={(v) => onChange({ ...value, version: Number(v) })}
      />
      <Field
        name="来源发生时间"
        type="datetime-local"
        required={false}
        value={value.occurred_at}
        onChange={(v) => onChange({ ...value, occurred_at: v })}
      />
      <Field
        name="来源凭据"
        value={value.evidence}
        onChange={(v) => onChange({ ...value, evidence: v })}
      />
    </fieldset>
  );
}
export function CommandForm<T extends CommandFields>({
  initial,
  title,
  save,
  children,
  canSubmit = () => true,
  onAcknowledged,
  onSaved,
  identity,
  ...props
}: WorkspaceProps & {
  initial: () => T;
  onAcknowledged?: WorkspaceProps["onChanged"];
  onSaved?: () => void;
  identity?: string;
  canSubmit?: (value: T) => boolean;
  title: string;
  save: string;
  children: (v: T, set: (v: T | ((current: T) => T)) => void) => ReactNode;
}) {
  const [value, setValue] = useState(initial),
    [version, setVersion] = useState(props.project.version),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [conflict, setConflict] = useState<WorkflowError | null>(null);
  const currentValue = useRef(value),
    pending = useRef<WorkflowCommand | null>(null),
    alive = useRef(true);
  const scope = useRef({api: props.api, projectId: props.project.id, identity});
  if (scope.current.api !== props.api || scope.current.projectId !== props.project.id || scope.current.identity !== identity) scope.current = {api: props.api, projectId: props.project.id, identity};
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      props.onDirty(title, false);
    };
  }, []);
  function set(v: T | ((current: T) => T)) {
    if (!alive.current) return;
    const next = typeof v === "function" ? v(currentValue.current) : v;
    currentValue.current = next;
    pending.current = null;
    setConflict(null);
    setValue(next);
    setDirty(true);
    props.onDirty(title, true);
  }
  return (
    <form
      aria-label={title}
      className="wf-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy || props.readOnly || !canSubmit(value)) return;
        setBusy(true);
        setError("");
        const submittedScope = scope.current;
        const current = () => alive.current && (!onAcknowledged || scope.current === submittedScope);
        try {
          if (!pending.current) {
            const fields = structuredClone(value);
            if ("source" in fields && fields.source) {
              const now = new Date().toISOString();
              fields.source = {
                ...fields.source,
                occurred_at: fields.source.occurred_at
                  ? new Date(fields.source.occurred_at).toISOString()
                  : now,
                collected_at: now,
                cutoff: fields.source.cutoff
                  ? new Date(fields.source.cutoff).toISOString()
                  : null,
              };
            }
            if (fields.action === "work_order.register") {
              fields.planned_start = new Date(
                fields.planned_start,
              ).toISOString();
              fields.planned_end = new Date(fields.planned_end).toISOString();
            }
            if (fields.action === "readiness.record")
              fields.valid_until = new Date(fields.valid_until).toISOString();
            pending.current = {
              ...fields,
              expected_version: version,
              operation_id: crypto.randomUUID(),
            };
          }
          const result = await props.api.command(
            props.project.id,
            pending.current,
          );
          onAcknowledged?.(result);
          if (current()) {
            setDirty(false);
            props.onDirty(title, false);
            if (onAcknowledged) onSaved?.(); else props.onChanged(result);
          }
        } catch (e) {
          if (current()) {
            setConflict(
              e instanceof WorkflowError && e.status === 409 ? e : null,
            );
            setError(
              e instanceof WorkflowError
                ? e.message +
                    (e.reasons.length ? " " + e.reasons.join("；") : "")
                : String(e),
            );
          }
        } finally {
          if (current()) setBusy(false);
        }
      }}
    >
      <h3>{title}</h3>
      <p>
        草稿依据：项目版本 {version}
        {dirty ? " · 未保存" : ""}
      </p>
      <fieldset disabled={busy || props.readOnly}>
        {children(value, set)}
      </fieldset>
      {error && <p role="alert">{error}</p>}
      {conflict && (
        <ConflictComparison
          api={props.api}
          projectId={props.project.id}
          version={version}
          error={conflict}
          draft={value}
          onRebase={(nextVersion)=>{
            if(!alive.current || nextVersion < version) return;
            setVersion(nextVersion);
            if(pending.current) pending.current={...pending.current,expected_version:nextVersion,operation_id:crypto.randomUUID()};
            setConflict(null);setError("");
          }}
        />
      )}
      <button
        disabled={busy || props.readOnly || !canSubmit(value)}
        type="submit"
      >
        {save}
      </button>
    </form>
  );
}
