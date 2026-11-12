// @vitest-environment jsdom
import { act } from "react";
import { expect, it, vi } from "vitest";
import { MaterialTaskPanel } from "./MaterialTaskPanel";
import { MaterialReferenceContext } from "./MaterialReferenceContext";
import { materialControlApi } from "./api";
import { MaterialReferenceOpen } from "./MaterialReferenceOpen";
import { project, flush } from "../testHelpers";
import { click, field, testRoot } from "./materialReferenceTestHelpers";
const pinned = {
  kind: "arrival",
  id: "a",
  version: 1
};
function task(version: number) {
  return {
    summary: {
      title: "核实",
      next_actions: []
    },
    value: {
      task_kind: "verify",
      state: "processing",
      note: "核对",
      assignee_id: "u",
      requirement_id: null,
      receipt_id: null,
      handoff_id: null,
      history: [],
      reference: {
        reference: pinned,
        title: "最初未匹配包裹",
        origin: "manual",
        environment: "unknown",
        receipt_id: null
      },
      reference_current: version === 1,
      current_reference: {
        ...pinned,
        version
      },
      reference_issue: "Arrival match changed",
    }
  };
}
function arrival(receipt: string | null, version: number) {
  return {
    summary: {
      id: "a",
      project_id: project.id
    },
    value: {
      kind: "arrival",
      id: "a",
      arrival_number: "A",
      location: "仓库",
      package_count: 1,
      description: "标签",
      state: receipt ? "matched" : "unlinked",
      receipt_id: receipt,
      matches: Array.from({
        length: version - 1
      }, () => ({
        receipt_id: receipt
      })),
    }
  };
}
function receiptItem(id: string, existing: string | null = null) {
  const reference = {
    kind: "receipt",
    id
  };
  return {
    reference,
    evidence: {
      reference,
      receipt_id: id,
      title: `收货 ${id}`,
      origin: "manual",
      environment: "unknown"
    },
    can_open: !existing,
    existing_task_id: existing
  };
}
function page(items: ReturnType<typeof receiptItem>[]) {
  return {
    project_id: project.id,
    project_version: 3,
    task_kind: "iqc",
    items,
    total: items.length
  };
}
function props(api: unknown) {
  return {
    api: api as never,
    project: {
      ...project,
      allowed_actions: ["material_task.open"] as any
    },
    readOnly: false,
    onChanged: vi.fn(),
    onDirty: vi.fn(),
    onOpen: vi.fn(),
    requestLeave: (f: () => void) => f()
  };
}
it("uses the current same-arrival match after v1 becomes v2 and after receipt correction", async () => {
  const v = testRoot();
  let version = 1, receipt: string | null = null;
  const api = {
    object: vi.fn(async (_p, kind) => kind === "arrival" ? arrival(receipt, version) : task(version)),
    materialAssignees: vi.fn().mockResolvedValue({
      items: []
    }),
    materialReferences: vi.fn(async () => page([receiptItem(receipt!)])),
  };
  const p = props(api);
  const render = async (projectVersion: number, allowed = true) => {
    await act(async () => v.root.render(<MaterialTaskPanel {...p} project={{
      ...p.project,
      version: projectVersion,
      allowed_actions: allowed ? ["material_task.open"] : []
    }} taskId="t"/>));
    await flush();
  };
  try {
    await render(3);
    expect(v.host.textContent).not.toContain("为关联收货安排检验");
    version = 2;
    receipt = "r1";
    await render(4);
    expect(v.host.textContent).toContain("最初未匹配包裹");
    await click(v.host, "为关联收货安排检验");
    expect(api.materialReferences).toHaveBeenLastCalledWith(project.id, "iqc", "", 1, 0, expect.any(AbortSignal), undefined, {
      receipt_id: "r1"
    });
    version = 3;
    receipt = "r2";
    await render(5);
    await click(v.host, "为关联收货安排检验");
    expect(api.materialReferences).toHaveBeenLastCalledWith(project.id, "iqc", "", 1, 0, expect.any(AbortSignal), undefined, {
      receipt_id: "r2"
    });
    await render(6, false);
    expect(v.host.textContent).not.toContain("为关联收货安排检验");
  }
  finally {
    await v.dispose();
  }
});
it("looks up an exact receipt beyond 1000 candidates and reuses its existing task", async () => {
  const v = testRoot();
  const api = {
    materialAssignees: vi.fn().mockResolvedValue({
      items: []
    }),
    materialReferences: vi.fn(async (_p, _k, _s, _l, _o, _signal, _req, options) => options?.receipt_id === "target-1001" ? page([receiptItem("target-1001", "existing")]) : {
      ...page([receiptItem("other")]),
      total: 1001
    }),
  };
  const p = props(api);
  try {
    await act(async () => v.root.render(<MaterialReferenceOpen p={p} resetRef={{
      current: () => {
      }
    }} fixedReceiptId="target-1001"/>));
    await click(v.host, "为关联收货安排检验");
    await flush();
    expect(api.materialReferences).toHaveBeenCalledTimes(1);
    await click(v.host, "打开已有任务");
    expect(p.onOpen).toHaveBeenCalledWith({
      projectId: project.id,
      kind: "material_task",
      id: "existing"
    });
  }
  finally {
    await v.dispose();
  }
});
it.each(["foreign-project", "wrong-arrival", "wrong-value-id", "inconsistent-match", "stale-version", "failed"])("does not use pinned or historical closure receipt when the current arrival read is %s", async (mode) => {
  const v = testRoot();
  const detail = {
    ...task(2),
    value: {
      ...task(2).value,
      reference: {
        ...task(2).value.reference,
        receipt_id: "historical"
      },
      closure: {
        resolved_evidence: {
          receipt_id: "historical"
        }
      },
    }
  };
  const current = arrival("r1", mode === "stale-version" ? 3 : 2);
  if (mode === "foreign-project")
    current.summary.project_id = "foreign";
  if (mode === "wrong-arrival")
    current.summary.id = "other";
  if (mode === "wrong-value-id")
    current.value.id = "other";
  if (mode === "inconsistent-match")
    current.value.matches[0].receipt_id = "other";
  const api = {
    object: vi.fn(async (_p, kind) => {
      if (kind === "material_task")
        return detail;
      if (mode === "failed")
        throw Error("读取失败");
      return current;
    }),
    materialAssignees: vi.fn().mockResolvedValue({
      items: []
    })
  };
  try {
    await act(async () => v.root.render(<MaterialTaskPanel {...props(api)} taskId="t"/>));
    await flush();
    expect(v.host.textContent).not.toContain("为关联收货安排检验");
    expect(v.host.textContent).toContain("最初未匹配包裹");
  }
  finally {
    await v.dispose();
  }
});
it.each(["api", "project", "reference"])("ignores a late current arrival response after %s changes", async (mode) => {
  const v = testRoot();
  let resolve!: (value: ReturnType<typeof arrival>) => void;
  const api = {
    object: vi.fn(async (_p, kind) => kind === "material_task" ? task(2) : new Promise<ReturnType<typeof arrival>>(r => {
      resolve = r;
    })),
    materialAssignees: vi.fn().mockResolvedValue({
      items: []
    }),
  };
  const nextApi = {
    ...api,
    object: vi.fn(async (_p, kind) => kind === "material_task" ? task(3) : arrival(null, 1))
  };
  const p = props(api);
  try {
    await act(async () => v.root.render(<MaterialTaskPanel {...p} taskId="t"/>));
    await flush();
    const oldResolve = resolve;
    if (mode === "reference")
      api.object.mockImplementation(async (_p, kind) => kind === "material_task" ? task(3) : arrival(null, 1));
    await act(async () => v.root.render(<MaterialTaskPanel {...p} taskId="t" api={(mode === "api" ? nextApi : api) as never} project={{
      ...p.project,
      id: mode === "project" ? "second" : project.id,
      version: mode === "reference" ? 4 : 3
    }}/>));
    await flush();
    await act(async () => oldResolve(arrival("old-r", 2)));
    expect(v.host.textContent).not.toContain("为关联收货安排检验");
  }
  finally {
    await v.dispose();
  }
});
it.each(["unavailable", "unauthorized", "failed", "missing-method", "wrong-receipt"])("does not fabricate a fixed receipt candidate for %s lookup", async (mode) => {
  const v = testRoot();
  const api = {
    materialAssignees: vi.fn().mockResolvedValue({
      items: []
    }),
    materialReferences: mode === "missing-method" ? undefined : vi.fn(async () => {
      if (mode === "failed" || mode === "unauthorized")
        throw Error(mode === "unauthorized" ? "404" : "读取失败");
      return page(mode === "wrong-receipt" ? [receiptItem("foreign")] : []);
    }),
  };
  try {
    await act(async () => v.root.render(<MaterialReferenceOpen p={props(api)} resetRef={{
      current: () => {
      }
    }} fixedReceiptId="r1"/>));
    await click(v.host, "为关联收货安排检验");
    await flush();
    expect(v.host.querySelector("[role=\"alert\"]")).not.toBeNull();
    expect(v.host.textContent).not.toContain("已选择");
    expect(v.host.textContent).not.toContain("创建检验任务");
  }
  finally {
    await v.dispose();
  }
});
it("shows both initial and current MES snapshot identities with the change reason", async () => {
  const v = testRoot();
  const old = {
    kind: "mes_component" as const,
    binding_id: "b",
    snapshot_id: "snapshot-old",
    component_key: "10"
  };
  try {
    await act(async () => v.root.render(<MaterialReferenceContext api={{} as never} projectId={project.id} projectVersion={3} evidence={{
      reference: old,
      title: "组件",
      origin: "native",
      environment: "test",
      version: "snapshot-old"
    } as never} current={false} currentReference={{
      ...old,
      snapshot_id: "snapshot-new"
    }} issue="MES observation changed"/>));
    expect(v.host.textContent).toContain("snapshot-old");
    expect(v.host.textContent).toContain("snapshot-new");
    expect(v.host.textContent).toContain("MES observation changed");
  }
  finally {
    await v.dispose();
  }
});
it("sends the exact receipt option through the existing GET reference API", async () => {
  const request = vi.fn().mockResolvedValue(page([]));
  const api = materialControlApi(request);
  await api.materialReferences(project.id, "iqc", "", 1, 0, undefined, undefined, {
    receipt_id: "receipt/1001"
  });
  const [path, method] = request.mock.calls[0];
  const url = new URL(path, "http://local.test");
  expect(url.pathname).toBe(`/projects/${project.id}/material-task-references`);
  expect(url.searchParams.get("receipt_id")).toBe("receipt/1001");
  expect(url.searchParams.get("limit")).toBe("1");
  expect(method).toBe("GET");
});
it("invalidates an arrival read when the same-scope reference generation changes", async () => {
  const v = testRoot();
  let resolve!: (value: ReturnType<typeof arrival>) => void;
  const api = {
    object: vi.fn().mockReturnValueOnce(new Promise(r => {
      resolve = r;
    })).mockResolvedValueOnce(arrival("r2", 3))
  };
  const evidence = task(2).value.reference;
  const render = async (version: number) => act(async () => v.root.render(<MaterialReferenceContext api={api as never} projectId={project.id} projectVersion={3} evidence={evidence as never} current={false} currentReference={{
    ...pinned,
    kind: "arrival",
    version
  }} issue="changed" renderCurrentReceipt={id => <p>当前收货 {id}</p>}/>));
  try {
    await render(2);
    await render(3);
    await flush();
    expect(v.host.textContent).toContain("当前收货 r2");
    await act(async () => resolve(arrival("r1", 2)));
    expect(v.host.textContent).toContain("当前收货 r2");
    expect(v.host.textContent).not.toContain("当前收货 r1");
  }
  finally {
    await v.dispose();
  }
});

it('retries a failed exact lookup when the coordinator opens the same receipt again', async () => {
  const v = testRoot();
  const api = {
    materialAssignees: vi.fn().mockResolvedValue({ items: [] }),
    materialReferences: vi.fn().mockRejectedValueOnce(Error('暂时不可用')).mockResolvedValueOnce(page([receiptItem('r1')])),
  };
  try {
    await act(async () => v.root.render(<MaterialReferenceOpen p={props(api)} resetRef={{ current: () => {} }} fixedReceiptId="r1" />));
    await click(v.host, '为关联收货安排检验');
    expect(v.host.textContent).toContain('暂时不可用');
    await click(v.host, '为关联收货安排检验');
    expect(api.materialReferences).toHaveBeenCalledTimes(2);
    expect(v.host.textContent).toContain('已选择：收货 r1');
  } finally { await v.dispose(); }
});

it('discards a late exact receipt lookup after the target changes', async () => {
  const v = testRoot();
  let resolve!: (value: ReturnType<typeof page>) => void;
  const api = {
    materialAssignees: vi.fn().mockResolvedValue({ items: [] }),
    materialReferences: vi.fn().mockReturnValueOnce(new Promise(r => { resolve = r; })).mockResolvedValueOnce(page([receiptItem('r2')])),
  };
  const p = props(api);
  const render = async (id: string) => act(async () => v.root.render(
    <MaterialReferenceOpen p={p} resetRef={{ current: () => {} }} fixedReceiptId={id} />));
  try {
    await render('r1');
    await click(v.host, '为关联收货安排检验');
    await render('r2');
    expect(v.host.textContent).toContain('收货关联已变化');
    expect(api.materialReferences).toHaveBeenCalledTimes(1);
    await click(v.host, '为关联收货安排检验');
    expect(v.host.textContent).toContain('已选择：收货 r2');
    await act(async () => resolve(page([receiptItem('r1')])));
    expect(v.host.textContent).not.toContain('收货 r1');
  } finally { await v.dispose(); }
});


it.each(["same-receipt", "foreign-response", "revoked"])(
  "retains the nested draft while a %s arrival refresh is unresolved",
  async mode => {
    const view = testRoot();
    let resolveArrival!: (value: ReturnType<typeof arrival>) => void;
    const api = {
      object: vi.fn(async (_project, kind) => kind === "material_task" ? task(2) : arrival("r1", 2)),
      materialAssignees: vi.fn().mockResolvedValue({ items: [{ id: "u", display_name: "李工" }] }),
      materialReferences: vi.fn(async () => page([receiptItem("r1")])),
      command: vi.fn(),
    };
    const p = props(api);
    const render = async (version: number, allowed = true) => {
      await act(async () => view.root.render(<MaterialTaskPanel {...p} taskId="t" project={{
        ...p.project, version, allowed_actions: allowed ? ["material_task.open"] : [],
      }} />));
      await flush();
    };
    const note = () => view.host.querySelector('[aria-label="核实任务说明"]') as HTMLInputElement | null;
    const submit = () => [...view.host.querySelectorAll("button")].find(b => b.textContent === "创建检验任务")!;
    try {
      await render(3);
      await click(view.host, "为关联收货安排检验");
      await field(view.host, "检验人", "u");
      await field(view.host, "核实任务说明", "保留草稿");
      api.object.mockImplementation(async (_project, kind) => kind === "material_task" ? task(2)
        : new Promise<ReturnType<typeof arrival>>(resolve => { resolveArrival = resolve; }));
      await render(4);
      expect(note()?.value).toBe("保留草稿");
      expect(submit().disabled).toBe(true);
      expect(view.host.textContent).not.toContain("观察位置 仓库");
      if (mode === "revoked") await render(4, false);
      const response = arrival("r1", 2);
      if (mode === "foreign-response") response.summary.project_id = "foreign";
      await act(async () => resolveArrival(response));
      expect(note()?.value).toBe("保留草稿");
      expect(submit().disabled).toBe(true);
      await click(view.host, "创建检验任务");
      expect(api.command).not.toHaveBeenCalled();
      if (mode === "same-receipt") {
        api.materialReferences.mockResolvedValue({ ...page([receiptItem("r1")]), project_version: 4 });
        await click(view.host, "重新核对所选收货");
        expect(note()?.value).toBe("保留草稿");
        expect(submit().disabled).toBe(false);
      } else {
        expect(view.host.textContent).not.toContain("重新核对所选收货");
        expect(view.host.textContent).not.toContain("为关联收货安排检验");
      }
    } finally { await view.dispose(); }
  },
);
