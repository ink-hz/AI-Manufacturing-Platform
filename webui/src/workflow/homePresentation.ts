import type { ActorTaskPage, Dashboard, OwnedTask, ProjectDetail } from './types';
import { statusTone } from './StatusBadge';
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const decimal = (value: unknown): value is string => typeof value === 'string' && /^\d+(\.\d+)?$/.test(value);
const positive = (value: string) => /[1-9]/.test(value);
export function homeMetrics(data: Dashboard | null, projects: ProjectDetail[], ready: boolean, tasks: ActorTaskPage | null) {
  const ids = new Set(data?.project_ids);
  const scopeReady = !!data && ready && data.project_count === ids.size && data.project_ids.length === ids.size && projects.length === ids.size && new Set(projects.map(p => p.id)).size === ids.size && projects.every(p => ids.has(p.id));
  const deliveryReady = scopeReady && projects.every(p => decimal(p.summary?.current_order_quantity) && decimal(p.summary?.remaining_to_ship));
  const qualityReady = scopeReady && projects.every(p => count(p.quality_summary?.open_nonconformances));
  const quality = qualityReady ? projects.reduce((sum, p) => sum + p.quality_summary!.open_nonconformances, 0) : null;
  return {
    delivery: deliveryReady ? projects.filter(p => positive(p.summary.current_order_quantity) && positive(p.summary.remaining_to_ship)).length : null,
    quality: count(quality) ? quality : null,
    workOrders: count(data?.counts.work_order) ? data!.counts.work_order : null,
    tasks: count(tasks?.total) ? tasks!.total : null,
    scopeReady,
  };
}
/** Stable sorting of the fetched page only; never a claimed global risk order. */
export function priorityTasks(items: OwnedTask[], limit = 6) {
  const rank = (task: OwnedTask) => ({danger: 0, warning: 1, info: 2, success: 2, neutral: 2})[statusTone(task.target.state, task.target.kind, task.target.blocking_reasons)];
  return items.map((task, index) => ({task, index})).sort((a, b) => rank(a.task) - rank(b.task) || a.index - b.index).slice(0, limit).map(({task}) => task);
}
export function taskScope(page: ActorTaskPage, shown: number) {
  return `本次读取 ${page.items.length} 条 · 展示 ${shown} 条 · ${page.truncated ? `可用事项至少 ${page.total} 条（下界；每项目查询有界）` : `事项合计 ${page.total} 条`}。仅在已读取页内按阻断、需关注、其他事项排序，同级保留原顺序；请查看全部事项继续翻页。`;
}
export function deliveryQuantity(project: ProjectDetail, key: 'remaining_to_ship' | 'remaining_to_accept') {
  const quantity = project.summary?.[key];
  return decimal(quantity) && project.unit?.code ? `${quantity} ${project.unit.code}` : '—';
}
