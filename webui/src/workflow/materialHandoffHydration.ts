import { WorkflowError, type WorkflowApi } from './api';
import type { ObjectDetail, ObjectSummary } from './types';

export interface HandoffRow {
  summary: ObjectSummary;
  detail?: ObjectDetail;
  batch?: string;
  error?: string;
  batchError?: string;
  loading: boolean;
}

// Each worker owns at most one request. Shared-lot promises belong only to this
// page; neither facts nor failures leak across project changes or later retries.
export async function hydrateHandoffPage(
  api: WorkflowApi,
  summaries: ObjectSummary[],
  signal: AbortSignal,
  onRow: (row: HandoffRow) => void,
) {
  const lots = new Map<string, Promise<string>>();
  let next = 0;
  function ordinary(error: unknown) {
    if (signal.aborted || (error instanceof WorkflowError && [401, 403].includes(error.status))) throw error;
    return String(error);
  }
  async function worker() {
    while (!signal.aborted && next < summaries.length) {
      const summary = summaries[next++];
      let detail: ObjectDetail;
      try {
        detail = await api.object(summary.project_id, 'material_handoff', summary.id, signal);
        if (detail.value.kind !== 'material_handoff') throw Error('交接记录类型不匹配');
      } catch (error) {
        const message = ordinary(error);
        if (!signal.aborted) onRow({summary, error: message, loading: false});
        continue;
      }
      if (signal.aborted) return;
      onRow({summary, detail, loading: true});
      const lotId = detail.value.kind === 'material_handoff' ? detail.value.material_lot_id : '';
      const key = `${summary.project_id}/${lotId}`;
      if (!lots.has(key)) {
        lots.set(key, api.object(summary.project_id, 'material_lot', lotId, signal).then(d => d.summary.title));
      }
      try {
        const batch = await lots.get(key)!;
        if (!signal.aborted) onRow({summary, detail, batch, loading: false});
      } catch (error) {
        const message = ordinary(error);
        if (!signal.aborted) onRow({summary, detail, batchError: message, loading: false});
      }
    }
  }
  await Promise.all(Array.from({length: Math.min(4, summaries.length)}, worker));
}
