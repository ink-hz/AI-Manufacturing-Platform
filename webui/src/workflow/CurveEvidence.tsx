import { useId } from "react";
import type { RawEvidence, Curve } from "./types";
import { origins } from "./forms/oemShared";
function Plot({ curve: c }: { curve: Curve }) {
  const id = useId();
  const points = c.points.map((p) => ({ x: Number(p.x), y: Number(p.y) }));
  const finite =
    points.length > 0 &&
    points.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  const xs = points.map((p) => p.x),
    ys = points.map((p) => p.y);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  const px = (x: number) => 50 + ((x - minX) / (maxX - minX || 1)) * 570,
    py = (y: number) => 190 - ((y - minY) / (maxY - minY || 1)) * 150;
  return (
    <section className="wf-curve">
      <h5>{c.name}</h5>
      {finite && (
        <svg role="img" aria-labelledby={id} viewBox="0 0 680 240">
          <title id={id}>
            {c.name} · 横轴 {c.x_unit} · 纵轴 {c.y_unit}；精确数值见下方表格
          </title>
          <path d="M50 30V190H630" fill="none" stroke="currentColor" />
          <polyline
            points={points.map((p) => `${px(p.x)},${py(p.y)}`).join(" ")}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          />
          {points.length === 1 && (
            <circle cx={px(points[0].x)} cy={py(points[0].y)} r="3" />
          )}
          <text x="300" y="228">
            横轴 ({c.x_unit})
          </text>
          <text x="55" y="20">
            纵轴 ({c.y_unit})
          </text>
        </svg>
      )}
      <div className="wf-table-scroll">
        <table>
          <caption>{c.name} · 原始精确数值</caption>
          <thead>
            <tr>
              <th>x ({c.x_unit})</th>
              <th>y ({c.y_unit})</th>
            </tr>
          </thead>
          <tbody>
            {c.points.map((p, i) => (
              <tr key={i}>
                <td>{p.x}</td>
                <td>{p.y}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
export function CurveEvidence({ value }: { value: RawEvidence }) {
  return (
    <section aria-label="原始曲线与日志">
      <h4>原始曲线与日志</h4>
      <p>{origins[value.origin]} · 曲线为已登记的有界证据</p>
      {value.curves.length ? (
        value.curves.map((curve, i) => <Plot key={i} curve={curve} />)
      ) : (
        <p>未登记曲线</p>
      )}
      {value.logs.map((log, i) => (
        <pre className="wf-evidence-log" key={i}>
          {log}
        </pre>
      ))}
    </section>
  );
}
