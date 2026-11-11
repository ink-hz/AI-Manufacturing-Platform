import { useState } from "react";
import type { BoardProps } from "./boards";
import { ReadBlock } from "./boards";
import {
  baseline,
  drill,
  editScope,
  localTime,
  useRead,
  type Location,
} from "./context";
import type { Aggregate, MissingField, ProductionRow } from "./types";
import "./versionUsage.css";

const combinationFields: MissingField[] = [
  "stage_id",
  "software_id",
  "software_version",
  "config_log_id",
  "config_version",
];
const combinationKey = (item: Aggregate) => JSON.stringify(combinationFields.map(field => item[field] ?? null));
function name(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}
function catalogName(rows: ProductionRow[] | undefined, id: string | null | undefined) {
  return id == null ? undefined : name(rows?.find(row => String(row.id) === id)?.name);
}

export function VersionUsageBoard({ api, location: l, go, refresh }: BoardProps) {
  const identity = JSON.stringify([l.projectId, l.scope]);
  const [selection, setSelection] = useState<{ identity: string; key: string }>();
  const versions = useRead(
    async signal => ({
      ...await api.productionAnalysis(l.projectId, { ...l.scope, view: "versions" }, signal),
      projectId: l.projectId,
      scope: l.scope,
    }),
    [api, l.projectId, l.scope, refresh],
    true,
    [api, l.projectId, l.scope],
  );
  // Names are optional: read one bounded page per directory and never walk it.
  const haveVersions = !!versions.data?.items.length;
  const software = useRead(
    signal => api.productionCatalog(l.projectId, "software", {}, signal),
    [api, l.projectId, refresh],
    haveVersions,
    [api, l.projectId],
  );
  const configs = useRead(
    signal => api.productionCatalog(l.projectId, "config_versions", {}, signal),
    [api, l.projectId, refresh],
    haveVersions,
    [api, l.projectId],
  );
  const selected = selection?.identity === identity
    ? versions.data?.items.find(item => combinationKey(item) === selection.key)
    : undefined;
  const selectedScope = selected && versions.data
    ? drill(baseline(versions.data.scope), selected, combinationFields)
    : undefined;
  const devices = useRead(
    signal => api.productionAnalysis(versions.data!.projectId, { ...selectedScope!, view: "devices" }, signal),
    [api, versions.data?.projectId, JSON.stringify(selectedScope), refresh],
    !!selectedScope,
    [api, versions.data?.projectId, JSON.stringify(selectedScope)],
  );
  const stageName = (item: Aggregate) => item.stage_id == null ? "未提供阶段" : name(item.stage_name) || l.labels[`stage_id:${item.stage_id}`] || "阶段名称未取得";
  const toolName = (item: Aggregate) => item.software_id == null ? "未提供工具" : name(item.software_name) || catalogName(software.data?.items, item.software_id) || l.labels[`software_id:${item.software_id}`] || "工具名称未取得";
  const configName = (item: Aggregate) => item.config_log_id == null ? "未提供配置" : catalogName(configs.data?.items, item.config_log_id) || "配置名称未取得";
  const open = (item: Aggregate, failure = false) => {
    if (!versions.data) return;
    const scope = drill(baseline(versions.data.scope), item, combinationFields);
    go({
      ...l,
      projectId: versions.data.projectId,
      view: "records",
      scope: failure ? editScope(scope, { status: "2" }) : scope,
      selectedError: false,
      selectedStage: false,
      savedSymptom: undefined,
      cursor: undefined,
      inherited: true,
    }, "scope");
  };
  const machineLocation = (item: Aggregate): Location => ({
    ...l,
    projectId: versions.data!.projectId,
    view: "device",
    scope: drill(selectedScope!, item, ["device"]),
    selectedError: false,
    selectedStage: false,
    savedSymptom: undefined,
    cursor: undefined,
    recentRange: undefined,
    inherited: true,
  });
  return <section className="pt-version-usage" aria-label="版本使用">
    <header className="pt-board-heading"><h3>版本使用</h3></header>
    <ReadBlock label="版本使用" state={versions}>{data => <>
      {!data.complete && <p className="pt-callout" role="status">部分结果未显示，请缩小范围</p>}
      {!data.items.length && data.complete && <p>本时段无版本使用记录</p>}
      {!!data.items.length && <div className="pt-table pt-version-table" role="region" aria-label="实际版本组合" tabIndex={0}><table>
        <thead><tr>{["生产阶段", "工具 / 版本", "配置 / 版本", "测试次数", "测试 SN", "失败 SN", "最近测试", "操作"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{data.items.map(item => <tr key={combinationKey(item)} aria-selected={selected === item}>
          <th scope="row">{stageName(item)}</th>
          <td>{toolName(item)}<span className="pt-version-value">{item.software_version ?? "未提供版本"}</span></td>
          <td>{configName(item)}<span className="pt-version-value">{item.config_version ?? "未提供版本"}</span></td>
          <td>{item.records}</td>
          <td>{item.distinct_sn}</td>
          <td data-failed={item.failed_sn !== "0"}>{item.failed_sn}</td>
          <td>{item.last_time ? localTime(item.last_time) : "未取得"}</td>
          <td><div className="pt-actions">
            <button type="button" onClick={() => open(item)}>查看测试</button>
            <button type="button" onClick={() => open(item, true)}>查看失败</button>
            <button type="button" aria-pressed={selected === item} onClick={() => setSelection({ identity, key: combinationKey(item) })}>查看上位机</button>
          </div></td>
        </tr>)}</tbody>
      </table></div>}
    </>}</ReadBlock>
    {selected && selectedScope && <section className="pt-version-devices" aria-label="组合使用位置">
      <header className="pt-board-heading"><h4>{toolName(selected)} · {selected.software_version ?? "未提供版本"} · {configName(selected)} · {selected.config_version ?? "未提供版本"}</h4><button type="button" onClick={() => setSelection(undefined)}>收起上位机</button></header>
      <ReadBlock label="组合上位机" state={devices}>{data => <>
        {!data.complete && <p className="pt-callout" role="status">部分上位机未显示，请缩小范围</p>}
        {!data.items.length && data.complete && <p>该组合暂无上位机记录</p>}
        {!!data.items.length && <div className="pt-table" role="region" aria-label="组合上位机分布" tabIndex={0}><table>
          <thead><tr>{["上位机", "测试次数", "测试 SN", "失败 SN", "最近测试", "操作"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>{data.items.map(item => <tr key={item.key}><th scope="row">{item.device ?? "未提供上位机"}</th><td>{item.records}</td><td>{item.distinct_sn}</td><td>{item.failed_sn}</td><td>{item.last_time ? localTime(item.last_time) : "未取得"}</td><td><button type="button" onClick={() => go(machineLocation(item), "scope")}>进入上位机</button></td></tr>)}</tbody>
        </table></div>}
      </>}</ReadBlock>
    </section>}
  </section>;
}
