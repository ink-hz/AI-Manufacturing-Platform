import type { Parameter, RawEvidence, Measurement, Origin } from "../types";
import { Field, Choice } from "./shared";
import { origins } from "./oemShared";
export function Parameters({
  name,
  value,
  onChange,
  lockedNames = false,
}: {
  name: string;
  value: Parameter[];
  onChange(v: Parameter[]): void;
  lockedNames?: boolean;
}) {
  return (
    <fieldset>
      <legend>{name}</legend>
      {value.map((r, i) => (
        <fieldset key={i}>
          <legend>
            {name} {i + 1}
          </legend>
          {lockedNames ? (
            <p>
              {r.name} · {r.unit}
            </p>
          ) : (
            <>
              <Field
                name={`${name}名称 ${i + 1}`}
                value={r.name}
                onChange={(x) =>
                  onChange(
                    value.map((a, n) => (n === i ? { ...a, name: x } : a)),
                  )
                }
              />
              <Field
                name={`${name}单位 ${i + 1}`}
                value={r.unit}
                onChange={(x) =>
                  onChange(
                    value.map((a, n) => (n === i ? { ...a, unit: x } : a)),
                  )
                }
              />
            </>
          )}
          <Field
            name={`${name}数值 ${i + 1}`}
            value={r.value}
            onChange={(x) =>
              onChange(value.map((a, n) => (n === i ? { ...a, value: x } : a)))
            }
          />
          {!lockedNames && (
            <button
              type="button"
              disabled={value.length === 1}
              onClick={() => onChange(value.filter((_, n) => n !== i))}
            >
              移除{name} {i + 1}
            </button>
          )}
        </fieldset>
      ))}
      {!lockedNames && (
        <button
          type="button"
          disabled={value.length >= 200}
          onClick={() =>
            onChange([...value, { name: "", value: "", unit: "" }])
          }
        >
          添加{name}
        </button>
      )}
    </fieldset>
  );
}
export function Measurements({
  value,
  onChange,
}: {
  value: Measurement[];
  onChange(v: Measurement[]): void;
}) {
  return (
    <fieldset>
      <legend>实际测量 · 固定修订限值</legend>
      {value.map((r, i) => (
        <div key={i}>
          <p>
            {r.name} · {r.unit} · 下限 {r.lower} · 上限 {r.upper}
          </p>
          <Field
            name={`实际测量值 ${i + 1}`}
            value={r.value}
            onChange={(x) =>
              onChange(value.map((a, n) => (n === i ? { ...a, value: x } : a)))
            }
          />
        </div>
      ))}
    </fieldset>
  );
}
export function RawFields({
  value: v,
  onChange: set,
}: {
  value: RawEvidence;
  onChange(v: RawEvidence): void;
}) {
  return (
    <fieldset>
      <legend>原始观察证据（有界）</legend>
      <Choice
        name="测试证据来源"
        value={v.origin}
        choices={origins}
        onChange={(x) => set({ ...v, origin: x as Origin })}
      />
      <p>人工录入或隔离模拟；不代表设备在线采集。</p>
      {v.curves.map((c, i) => (
        <fieldset key={i}>
          <legend>曲线 {i + 1}</legend>
          <Field
            name={`曲线名称 ${i + 1}`}
            value={c.name}
            onChange={(x) =>
              set({
                ...v,
                curves: v.curves.map((a, n) =>
                  n === i ? { ...a, name: x } : a,
                ),
              })
            }
          />
          <Field
            name={`横轴单位 ${i + 1}`}
            value={c.x_unit}
            onChange={(x) =>
              set({
                ...v,
                curves: v.curves.map((a, n) =>
                  n === i ? { ...a, x_unit: x } : a,
                ),
              })
            }
          />
          <Field
            name={`纵轴单位 ${i + 1}`}
            value={c.y_unit}
            onChange={(x) =>
              set({
                ...v,
                curves: v.curves.map((a, n) =>
                  n === i ? { ...a, y_unit: x } : a,
                ),
              })
            }
          />
          {c.points.map((pt, j) => (
            <div key={j}>
              {(["x", "y"] as const).map((axis) => (
                <Field
                  key={axis}
                  name={`曲线 ${i + 1} 点 ${j + 1} ${axis}`}
                  value={pt[axis]}
                  onChange={(x) =>
                    set({
                      ...v,
                      curves: v.curves.map((a, n) =>
                        n === i
                          ? {
                              ...a,
                              points: a.points.map((b, m) =>
                                m === j ? { ...b, [axis]: x } : b,
                              ),
                            }
                          : a,
                      ),
                    })
                  }
                />
              ))}
              <button
                type="button"
                disabled={c.points.length === 1}
                onClick={() =>
                  set({
                    ...v,
                    curves: v.curves.map((a, n) =>
                      n === i
                        ? { ...a, points: a.points.filter((_, m) => m !== j) }
                        : a,
                    ),
                  })
                }
              >
                移除曲线 {i + 1} 点 {j + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            disabled={
              c.points.length >= 2000 ||
              v.curves.reduce((n, a) => n + a.points.length, 0) >= 10000
            }
            onClick={() =>
              set({
                ...v,
                curves: v.curves.map((a, n) =>
                  n === i
                    ? { ...a, points: [...a.points, { x: "", y: "" }] }
                    : a,
                ),
              })
            }
          >
            添加曲线 {i + 1} 数据点
          </button>
          <button
            type="button"
            onClick={() =>
              set({ ...v, curves: v.curves.filter((_, n) => n !== i) })
            }
          >
            移除曲线 {i + 1}
          </button>
        </fieldset>
      ))}
      <button
        type="button"
        disabled={v.curves.length >= 10}
        onClick={() =>
          set({
            ...v,
            curves: [
              ...v.curves,
              { name: "", x_unit: "", y_unit: "", points: [{ x: "", y: "" }] },
            ],
          })
        }
      >
        添加观察曲线
      </button>
      {v.logs.map((log, i) => (
        <div key={i}>
          <Field
            name={`原始日志 ${i + 1}`}
            value={log}
            required={false}
            onChange={(x) =>
              set({ ...v, logs: v.logs.map((a, n) => (n === i ? x : a)) })
            }
          />
          <button
            type="button"
            onClick={() =>
              set({ ...v, logs: v.logs.filter((_, n) => n !== i) })
            }
          >
            移除日志 {i + 1}
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={v.logs.length >= 100}
        onClick={() => set({ ...v, logs: [...v.logs, ""] })}
      >
        添加原始日志
      </button>
      <p>
        最多 10 条曲线、每条 2000 点、合计 10000 点；横轴必须递增。日志合计最多
        16000 字符。
      </p>
    </fieldset>
  );
}
