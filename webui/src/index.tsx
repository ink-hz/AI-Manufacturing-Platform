import { createRoot } from "react-dom/client";
import { App } from "./App";
import type { MountOptions } from "./types";
import "./manufacturing.css";
export type { MountOptions } from "./types";
export function mount(element: HTMLElement, options: MountOptions) {
  const root = createRoot(element);
  let dirty = false,
    unmounted = false;
  root.render(
    <App
      options={{
        ...options,
        onAuthError() {
          if (!unmounted) options.onAuthError?.();
        },
        onDirtyChange(value) {
          if (unmounted) return;
          dirty = value;
          options.onDirtyChange?.(value);
        },
      }}
    />,
  );
  return {
    isDirty: () => dirty,
    unmount() {
      if (unmounted) return;
      unmounted = true;
      root.unmount();
      dirty = false;
      options.onDirtyChange?.(false);
    },
  };
}
