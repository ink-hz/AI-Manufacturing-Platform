import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect } from 'vitest';

export function testRoot() {
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  return {
    host, root,
    dispose: async () => { await act(async () => root.unmount()); host.remove(); },
  };
}

export async function click(host: HTMLElement, label: string) {
  const button = [...host.querySelectorAll('button')].find(b => b.textContent === label);
  expect(button, `button ${label}`).toBeTruthy();
  await act(async () => button!.click());
}

export async function field(host: HTMLElement, label: string, value: string) {
  await act(async () => {
    const input = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement | HTMLSelectElement;
    expect(input, `field ${label}`).toBeTruthy();
    if (input instanceof HTMLSelectElement) {
      input.value = value;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
}
