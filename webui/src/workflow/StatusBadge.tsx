import type { ObjectKind, ObjectSummary } from './types';
import { label } from './labels';
export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';
/** Object states only: accepted/running never imply completion of the project. */
export function statusTone(state: string, kind?: ObjectKind, blocking: readonly string[] = []): StatusTone {
  if (state === 'blocked' || state === 'rejected' || (kind === 'test' && state === 'fail') || (kind === 'nonconformance' && state === 'open')) return 'danger';
  if (blocking.length || ['held', 'frozen', 'stopped', 'stop_requested', 'mes_accepted_held', 'partially_resumed', 'partial'].includes(state)) return 'warning';
  if (['cancelled', 'superseded', 'stop_superseded', 'draft', 'unknown', 'not_required', 'na'].includes(state)) return 'neutral';
  if (['complete', 'completed', 'closed', 'resolved', 'approved', 'verified'].includes(state) || (kind === 'test' && state === 'pass')) return 'success';
  if (['pending', 'start_pending', 'rework'].includes(state) || (state === 'open' && ['rma', 'capa', 'eco', 'rework'].includes(kind || ''))) return 'warning';
  if (['accepted', 'running', 'resumed', 'active', 'ready', 'requested', 'confirmed', 'received', 'posted', 'validated', 'applied'].includes(state)) return 'info';
  return 'neutral';
}
export function needsAttention(value: Pick<ObjectSummary, 'state' | 'kind' | 'blocking_reasons'>) {
  return ['danger', 'warning'].includes(statusTone(value.state, value.kind, value.blocking_reasons));
}
const paths: Record<StatusTone, string> = {
  neutral: 'M5 12h14', info: 'M12 10v7M12 6v1', success: 'm5 12 4 4L19 6',
  warning: 'M12 7v6M12 16v1M12 3 2 21h20Z', danger: 'm7 7 10 10M7 17 17 7',
};
export function StatusBadge({state, kind, blocking = []}: {state: string; kind?: ObjectKind; blocking?: readonly string[]}) {
  const tone = statusTone(state, kind, blocking);
  return <span className={`wf-status wf-status-${tone}`}>
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d={paths[tone]}/></svg>
    {label(state)}
  </span>;
}
