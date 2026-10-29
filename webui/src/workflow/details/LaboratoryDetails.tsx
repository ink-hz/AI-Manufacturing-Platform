import type { ObjectDetail, Parameter } from "../types";
import { useEffect, useState } from "react";
import type { WorkflowApi } from "../api";
import { label } from "../labels";
import { CurveEvidence } from "../CurveEvidence";
import { Source } from "../WorkflowDetail";
export function ParameterTable({
  title,
  items,
}: {
  title: string;
  items: Parameter[];
}) {
  return (
    <table>
      <caption>{title}</caption>
      <thead>
        <tr>
          <th>名称</th>
          <th>数值</th>
          <th>单位</th>
        </tr>
      </thead>
      <tbody>
        {items.map((r) => (
          <tr key={r.name}>
            <td>{r.name}</td>
            <td>{r.value}</td>
            <td>{r.unit}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
function CurrentQualification({
  api,
  projectId,
  testId,
}: {
  api?: WorkflowApi;
  projectId: string;
  testId: string | null;
}) {
  const [value, setValue] = useState<Extract<
    ObjectDetail["value"],
    { kind: "test" }
  > | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setValue(null);
    setError("");
    if (api && testId)
      api
        .object(projectId, "test", testId, controller.signal)
        .then((detail) => {
          if (!controller.signal.aborted && detail.value.kind === "test")
            setValue(detail.value);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(String(e));
        });
    return () => controller.abort();
  }, [api, projectId, testId, retry]);
  if (!testId) return <p>当前测试资格：没有完成的关联测试</p>;
  if (!api) return <p>当前测试资格：待核对关联质量测试</p>;
  if (error)
    return (
      <p role="alert">
        当前资格读取失败：{error}
        <button onClick={() => setRetry((n) => n + 1)}>重试当前资格</button>
      </p>
    );
  if (!value) return <p role="status">正在核对当前测试资格…</p>;
  return (
    <section>
      <p>
        当前测试资格：
        {value.current_qualified === true
          ? "有效"
          : value.current_qualified === false
            ? "无效"
            : "未知"}
      </p>
      {value.current_blocking_reasons?.map((reason, i) => (
        <p key={i}>{reason}</p>
      ))}
      <p>当前测试资格不代替独立质量放行或客户放行。</p>
    </section>
  );
}
export function LaboratoryDetails({
  data,
  api,
}: {
  data: ObjectDetail;
  api?: WorkflowApi;
}) {
  const v = data.value;
  if (v.kind === "test_plan")
    return (
      <section>
        <p>
          层级 {v.level} · 工位 {v.station} · 设备 {v.equipment} · 治具{" "}
          {v.fixture}
        </p>
        <p>
          算法 {v.algorithm_version} · 固件 {v.firmware_version} · 修订摘要{" "}
          {v.revision_hash}
        </p>
        <p>
          测试规范 {v.test_spec.version} · 程序 {v.test_spec.program_version}
        </p>
        <table>
          <thead>
            <tr>
              <th>测量</th>
              <th>单位</th>
              <th>下限</th>
              <th>上限</th>
            </tr>
          </thead>
          <tbody>
            {v.test_spec.measurements.map((m) => (
              <tr key={m.name}>
                <td>{m.name}</td>
                <td>{m.unit}</td>
                <td>{m.lower}</td>
                <td>{m.upper}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          {v.actor_id} · {v.recorded_at}
        </p>
      </section>
    );
  if (v.kind === "test_run")
    return (
      <section>
        <p>
          运行生命周期：{v.state === "running" ? "运行登记中" : label(v.state)}{" "}
          · 运行次数 {v.attempt}
        </p>
        <p>历史判定：{v.outcome ? label(v.outcome) : "无判定"}</p>
        <CurrentQualification
          api={api}
          projectId={data.summary.project_id}
          testId={v.test_id}
        />
        <p>
          当前资格与质量阻断：
          {data.summary.blocking_reasons.length
            ? data.summary.blocking_reasons.join("；")
            : "请核对关联质量测试的当前资格；历史判定不等于放行。"}
        </p>
        <p>
          程序 {v.scope.program_version} · 测试规范 {v.scope.test_version} ·
          固件 {v.scope.firmware_version} · 执行范围 {v.scope.route_fingerprint}
        </p>
        <p>
          开始登记 {v.actor_id} · {v.recorded_at}
        </p>
        {v.finish && (
          <>
            <p>
              结果登记 {v.finish.actor_id} · {v.finish.recorded_at} ·{" "}
              {v.finish.evidence}
            </p>
            <ParameterTable title="实际测量" items={v.finish.measurements} />
            <table>
              <caption>固定限值</caption>
              <thead>
                <tr>
                  <th>测量</th>
                  <th>下限</th>
                  <th>上限</th>
                </tr>
              </thead>
              <tbody>
                {v.finish.measurements.map((r) => (
                  <tr key={r.name}>
                    <td>{r.name}</td>
                    <td>{r.lower}</td>
                    <td>{r.upper}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Source value={v.finish.source} />
          </>
        )}
        {v.raw && <CurveEvidence value={v.raw} />}
        <p>原始证据摘要：{v.raw_digest || "尚无结果证据"}</p>
      </section>
    );
  if (v.kind === "calibration")
    return (
      <section>
        <p>
          标定状态：
          {v.state === "pending" ? "待独立读回确认" : "已登记匹配读回证据"}
        </p>
        <p>
          算法 {v.algorithm_version} · {label(v.origin)} · 来源{" "}
          {v.source_identity} · 版本 {v.source_version}
        </p>
        <ParameterTable title="登记参数" items={v.parameters} />
        <p>
          {v.evidence} · {v.actor_id} · {v.recorded_at} · 摘要{" "}
          {v.parameter_digest}
        </p>
        {v.confirmation && (
          <section>
            <h4>独立读回确认</h4>
            <ParameterTable
              title="实际读回参数"
              items={v.confirmation.readback}
            />
            <p>
              {label(v.confirmation.origin)} · 来源{" "}
              {v.confirmation.source_identity} · 版本{" "}
              {v.confirmation.source_version}
            </p>
            <p>
              {v.confirmation.evidence} · {v.confirmation.actor_id} ·{" "}
              {v.confirmation.recorded_at} · 摘要{" "}
              {v.confirmation.parameter_digest}
            </p>
          </section>
        )}
        <p>以上是人工登记或隔离模拟的证据，不表示平台对设备执行写入或读取。</p>
      </section>
    );
  if (v.kind === "component_link")
    return (
      <section>
        <p>
          部件 {v.material_id} · 序列号 {v.component_serial} · {label(v.state)}{" "}
          · {label(v.origin)}
        </p>
        <p>
          安装 {v.evidence} · {v.actor_id} · {v.recorded_at}
        </p>
        {v.removal && (
          <p>
            拆除 {v.removal.evidence} · {v.removal.actor_id} ·{" "}
            {v.removal.recorded_at}
          </p>
        )}
      </section>
    );
  return null;
}
