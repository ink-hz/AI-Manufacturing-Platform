import type { RecordContent } from "../types";
type Kind = "participants" | "handoffs" | "systems";
const schema = {
  participants: {
    label: "参与方",
    fields: [
      ["name", "名称"],
      ["role", "角色"],
      ["responsibility", "责任"],
    ],
  },
  handoffs: {
    label: "交接资料",
    fields: [
      ["name", "资料或数据名"],
      ["from_party", "提供方"],
      ["to_party", "接收方"],
      ["version_reference", "版本/依据"],
      ["notes", "说明"],
    ],
  },
  systems: {
    label: "系统",
    fields: [
      ["name", "名称"],
      ["kind", "类型"],
      ["objects", "相关数据"],
      ["maintainer", "维护方"],
      ["method", "交换方式"],
      ["notes", "说明"],
    ],
  },
} as const;
const methods = { unknown: "待确认", manual: "人工", file: "文件", api: "API" };
export function RelationshipsEditor({
  value,
  editing,
  disabled,
  onChange,
}: {
  value: RecordContent;
  editing: boolean;
  disabled: boolean;
  onChange: (value: RecordContent) => void;
}) {
  function update(kind: Kind, index: number, field: string, text: string) {
    onChange({
      ...value,
      [kind]: value[kind].map((r, i) =>
        i === index ? { ...r, [field]: text } : r,
      ),
    });
  }
  return (
    <div className="mf-relations">
      {(Object.keys(schema) as Kind[]).map((kind) => {
        const section = schema[kind];
        return (
          <section key={kind} aria-label={section.label}>
            <div className="mf-section-heading">
              <h3>{section.label}</h3>
              {editing && (
                <button
                  type="button"
                  disabled={disabled || value[kind].length >= 20}
                  onClick={() =>
                    onChange({
                      ...value,
                      [kind]: [
                        ...value[kind],
                        Object.fromEntries(
                          section.fields.map(([key]) => [
                            key,
                            key === "method" ? "unknown" : "",
                          ]),
                        ),
                      ],
                    })
                  }
                >
                  添加{section.label}
                </button>
              )}
            </div>
            {kind === "systems" && (
              <p className="mf-badge">关系登记，尚未验证连接</p>
            )}
            {!value[kind].length && (
              <p className="mf-muted">尚未登记{section.label}。</p>
            )}
            {value[kind].map((row, index) => (
              <fieldset className="mf-relation-row" key={index}>
                <legend>
                  {section.label} {index + 1}
                </legend>
                {section.fields.map(([key, label]) => {
                  const text = (row as unknown as Record<string, string>)[key];
                  return editing ? (
                    <label key={key}>
                      {label}
                      {key === "method" ? (
                        <select
                          aria-label={`${section.label} ${index + 1} ${label}`}
                          disabled={disabled}
                          value={text}
                          onChange={(e) =>
                            update(kind, index, key, e.target.value)
                          }
                        >
                          {Object.entries(methods).map(([id, name]) => (
                            <option key={id} value={id}>
                              {name}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          required={key === "name"}
                          maxLength={500}
                          aria-label={`${section.label} ${index + 1} ${label}`}
                          disabled={disabled}
                          value={text}
                          onChange={(e) =>
                            update(kind, index, key, e.target.value)
                          }
                        />
                      )}
                    </label>
                  ) : (
                    <div key={key}>
                      <span className="mf-muted">{label}：</span>
                      {key === "method"
                        ? methods[text as keyof typeof methods]
                        : text || "未填写"}
                    </div>
                  );
                })}
                {editing && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() =>
                      onChange({
                        ...value,
                        [kind]: value[kind].filter((_, i) => i !== index),
                      })
                    }
                  >
                    移除{section.label} {index + 1}
                  </button>
                )}
              </fieldset>
            ))}
          </section>
        );
      })}
    </div>
  );
}
