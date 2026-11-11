import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { useRead } from "./context";

it("restarts a pending read when only its logical identity changes", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const requests: { signal: AbortSignal; finish: (value: string) => void }[] = [];
  function Reader({ identity }: { identity: string }) {
    const state = useRead(signal => new Promise<string>(finish => requests.push({ signal, finish })), ["same-query"], true, [identity]);
    return <div>{state.loading ? "加载中" : state.data || state.error}</div>;
  }
  try {
    await act(async () => root.render(<Reader identity="live" />));
    expect(requests).toHaveLength(1);
    await act(async () => root.render(<Reader identity="fixed" />));
    expect(requests).toHaveLength(2);
    expect(requests[0].signal.aborted).toBe(true);
    await act(async () => requests[0].finish("旧内容"));
    expect(host.textContent).toBe("加载中");
    await act(async () => requests[1].finish("当前内容"));
    expect(host.textContent).toBe("当前内容");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
