import { createRoot } from "react-dom/client";
import { App } from "./App";
import type { MountOptions, WorkbenchUser } from "./types";
import "./manufacturing.css";
export type { MountOptions, WorkbenchUser } from "./types";
export function mount(element: HTMLElement, options: MountOptions) {
  const root = createRoot(element);
  let dirty = false,
    unmounted = false;
  const mountedOptions: MountOptions = {
    ...options,
    onAuthError() {
      if (!unmounted) options.onAuthError?.();
    },
    onDirtyChange(value) {
      if (unmounted) return;
      dirty = value;
      options.onDirtyChange?.(value);
    },
    onNavigatePlatform:
      options.onNavigatePlatform &&
      (() => {
        if (!unmounted) options.onNavigatePlatform?.();
      }),
    onLogout:
      options.onLogout &&
      (async () => {
        if (!unmounted) await options.onLogout?.();
      }),
  };
  const render = () => root.render(<App options={mountedOptions} />);
  render();
  return {
    isDirty: () => dirty,
    updateUser(user: WorkbenchUser) {
      if (unmounted) return;
      mountedOptions.user = user;
      render();
    },
    unmount() {
      if (unmounted) return;
      unmounted = true;
      root.unmount();
      dirty = false;
      options.onDirtyChange?.(false);
    },
  };
}
