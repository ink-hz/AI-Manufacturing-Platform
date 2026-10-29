import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { StatusBadge, statusTone, needsAttention } from './StatusBadge';
it('uses explicit state and kind, never title inference or completion guesses', () => {
  expect(statusTone('open', 'nonconformance')).toBe('danger');
  expect(statusTone('open', 'order_line')).toBe('neutral');
  expect(statusTone('fail', 'test')).toBe('danger');
  expect(statusTone('accepted', 'exchange')).toBe('info');
  expect(statusTone('running', 'unit')).toBe('info');
  for (const state of ['complete', 'closed', 'resolved']) expect(statusTone(state)).toBe('success');
  for (const state of ['cancelled','superseded','draft','unknown','未完成','new_future_state']) expect(statusTone(state)).toBe('neutral');
  expect(statusTone('active','work_order',['missing evidence'])).toBe('warning');
  expect(needsAttention({state:'open',kind:'nonconformance',blocking_reasons:[]})).toBe(true);
  expect(needsAttention({state:'accepted',kind:'exchange',blocking_reasons:[]})).toBe(false);
});
it('retains readable actual state and a non-color icon', () => {
  const html=renderToStaticMarkup(<StatusBadge state="accepted" kind="exchange"/>);
  expect(html).toContain('接收'); expect(html).toContain('<svg'); expect(html).not.toContain('已完成');
  expect(renderToStaticMarkup(<StatusBadge state="future"/>)).toContain('future');
});
