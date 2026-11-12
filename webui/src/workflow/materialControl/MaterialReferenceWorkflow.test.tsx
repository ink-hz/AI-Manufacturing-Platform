// @vitest-environment jsdom
import { act } from "react";
import { expect, it, vi } from "vitest";
import { bootstrap, project, workflowView } from "../testHelpers";
it("isolates a delayed reference read after the API connection changes in WorkflowApp", async () => {
  const oem = {
    ...project,
    mode: "oem" as const,
    allowed_actions: ["material_task.open"] as const
  };
  const page = {
    project_id: project.id,
    project_version: 3,
    read_at: "",
    coverage_issues: [],
    source_modes: [],
    work_orders: [],
    requirements: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    material_task_counts: {},
    total: 0,
    scope_total: 0,
    problem_counts: {
      attention: 0
    },
    limit: 50,
    offset: 0
  };
  const v = await workflowView({
    initial: "制造项目",
    readProjects: async () => [oem as any],
    readProject: async () => oem as any,
    readMaterialProject: async () => page
  });
  const original = globalThis.fetch;
  let resolve!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    const url = String(input);
    if (url.includes("/material-task-references?"))
      return new Promise<Response>(r => {
        resolve = r;
      });
    if (url.includes("/material-control/assignees?"))
      return new Response(JSON.stringify({
        items: [],
        total: 0
      }));
    return original(input, init);
  }));
  try {
    await v.click("供应与物料");
    await v.click("安排核实");
    await v.rerender({
      csrfToken: "changed-token"
    });
    await act(async () => resolve(new Response(JSON.stringify({
      project_id: project.id,
      task_kind: "verify",
      project_version: 3,
      items: [{
          reference: {
            kind: "receipt",
            id: "old"
          },
          evidence: {
            title: "旧连接记录",
            origin: "mock",
            environment: "test"
          },
          can_open: true,
          existing_task_id: null
        }],
      total: 1
    }))));
    await new Promise(r => setTimeout(r, 0));
    expect(v.host.textContent).not.toContain("旧连接记录");
  }
  finally {
    await v.dispose();
  }
});
it("does not display an old actor reference after the user changes in WorkflowApp", async () => {
  const oem = {
    ...project,
    mode: "oem" as const,
    allowed_actions: ["material_task.open"] as const
  };
  const page = {
    project_id: project.id,
    project_version: 3,
    read_at: "",
    coverage_issues: [],
    source_modes: [],
    work_orders: [],
    requirements: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    material_task_counts: {},
    total: 0,
    scope_total: 0,
    problem_counts: {
      attention: 0
    },
    limit: 50,
    offset: 0
  };
  const v = await workflowView({
    initial: "制造项目",
    readProjects: async () => [oem as any],
    readProject: async () => oem as any,
    readMaterialProject: async () => page
  });
  const original = globalThis.fetch;
  let resolve!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    const url = String(input);
    if (url.includes("/material-task-references?"))
      return new Promise<Response>(r => {
        resolve = r;
      });
    if (url.includes("/material-control/assignees?"))
      return new Response(JSON.stringify({
        items: [],
        total: 0
      }));
    return original(input, init);
  }));
  try {
    await v.click("供应与物料");
    await v.click("安排核实");
    await v.rerender({
      bootstrap: {
        ...bootstrap,
        user: {
          id: "another",
          display_name: "另一人"
        }
      }
    });
    await act(async () => resolve(new Response(JSON.stringify({
      project_id: project.id,
      task_kind: "verify",
      project_version: 3,
      items: [{
          reference: {
            kind: "receipt",
            id: "old"
          },
          evidence: {
            title: "旧用户记录",
            origin: "mock",
            environment: "test"
          },
          can_open: true,
          existing_task_id: null
        }],
      total: 1
    }))));
    await new Promise(r => setTimeout(r, 0));
    expect(v.host.textContent).not.toContain("旧用户记录");
  }
  finally {
    await v.dispose();
  }
});
it("records a package and selects it for verification in the real WorkflowApp", async () => {
  let version = 3, recorded = false;
  const oem = {
    ...project,
    mode: "oem" as const,
    allowed_actions: ["material_task.open", "arrival.record"] as const
  };
  const page = () => ({
    project_id: project.id,
    project_version: version,
    read_at: "",
    coverage_issues: [],
    source_modes: [],
    work_orders: [],
    requirements: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    material_task_counts: {},
    total: 0,
    scope_total: 0,
    problem_counts: {
      attention: 0
    },
    limit: 50,
    offset: 0
  });
  const v = await workflowView({
    initial: "制造项目",
    readProjects: async () => [oem as any],
    readProject: async () => ({
      ...oem,
      version
    }) as any,
    readMaterialProject: async () => page()
  });
  const original = globalThis.fetch;
  const ref = {
    kind: "arrival",
    id: "a",
    version: 1
  };
  const commands: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    const url = String(input);
    if (url.includes("/material-task-references?"))
      return new Response(JSON.stringify({
        project_id: project.id,
        task_kind: "verify",
        project_version: version,
        items: recorded ? [{
            reference: ref,
            evidence: {
              reference: ref,
              title: "包裹 A",
              origin: "manual",
              environment: "unknown",
              receipt_id: null,
              work_order_id: null
            },
            can_open: true,
            existing_task_id: null
          }] : [],
        total: recorded ? 1 : 0
      }));
    if (url.includes("/material-control/assignees?"))
      return new Response(JSON.stringify({
        items: [{
            id: "u",
            display_name: "李工"
          }],
        total: 1
      }));
    if (url.includes("/objects/arrival/a"))
      return new Response(JSON.stringify({
        summary: {
          id: "a",
          project_id: project.id
        },
        value: {
          kind: "arrival",
          id: "a",
          arrival_number: "A",
          location: "收货区",
          package_count: 2,
          description: "标签轴承",
          state: "unlinked"
        }
      }));
    if (url.endsWith("/commands")) {
      commands.push(JSON.parse(String(init?.body)));
      recorded = true;
      version = 4;
      return new Response(JSON.stringify({
        project_id: project.id,
        project_version: 4,
        object_type: "arrival",
        object_id: "a"
      }));
    }
    return original(input, init);
  }));
  try {
    await v.click("供应与物料");
    await v.click("安排核实");
    await v.click("记录实际包裹");
    await v.field("到件编号", "A");
    await v.field("观察位置", "收货区");
    await v.field("包裹数", "2");
    await v.field("实物描述", "标签轴承");
    await v.click("保存观察");
    expect(commands[0].action).toBe("arrival.record");
    await v.click("包裹 A");
    expect(v.host.textContent).toContain("观察位置 收货区");
    expect(v.host.textContent).toContain("待关联收货");
    expect(v.host.querySelector("[aria-label=\"核实人\"]")).not.toBeNull();
  }
  finally {
    await v.dispose();
  }
});
it("does not show a delayed reference from the previous project", async () => {
  const first = {
    ...project,
    mode: "oem" as const,
    allowed_actions: ["material_task.open"] as const
  };
  const second = {
    ...first,
    id: "second",
    name: "第二项目"
  };
  let resolve!: (r: Response) => void;
  const page = (id: string) => ({
    project_id: id,
    project_version: 3,
    read_at: "",
    coverage_issues: [],
    source_modes: [],
    work_orders: [],
    requirements: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    material_task_counts: {},
    total: 0,
    scope_total: 0,
    problem_counts: {
      attention: 0
    },
    limit: 50,
    offset: 0
  });
  const v = await workflowView({
    initial: "制造项目",
    readProjects: async () => [first as any, second as any],
    readProject: async () => first as any,
    readMaterialProject: async (_offset, id) => page(id)
  });
  const original = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/projects/second"))
      return new Response(JSON.stringify(second));
    if (url.includes("/material-task-references?"))
      return new Promise<Response>(r => {
        resolve = r;
      });
    if (url.includes("/material-control/assignees?"))
      return new Response(JSON.stringify({
        items: [],
        total: 0
      }));
    return original(input, init);
  }));
  try {
    await v.click("供应与物料");
    await v.click("安排核实");
    await v.click("返回项目列表");
    await v.click("第二项目");
    await v.click("供应与物料");
    await act(async () => resolve(new Response(JSON.stringify({
      project_id: project.id,
      task_kind: "verify",
      project_version: 3,
      items: [{
          reference: {
            kind: "receipt",
            id: "old"
          },
          evidence: {
            title: "旧项目记录",
            origin: "mock",
            environment: "test"
          },
          can_open: true,
          existing_task_id: null
        }],
      total: 1
    }))));
    await new Promise(r => setTimeout(r, 0));
    expect(v.host.textContent).toContain("第二项目");
    expect(v.host.textContent).not.toContain("旧项目记录");
  }
  finally {
    await v.dispose();
  }
});
it("acknowledges an earlier save without clearing a newer verification draft in WorkflowApp", async () => {
  const oem = {
    ...project,
    mode: "oem" as const,
    allowed_actions: ["material_task.open"] as const
  };
  let version = 3, resolve!: (r: Response) => void;
  const page = () => ({
    project_id: project.id,
    project_version: version,
    read_at: "",
    coverage_issues: [],
    source_modes: [],
    work_orders: [],
    requirements: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    material_task_counts: {},
    total: 0,
    scope_total: 0,
    problem_counts: {
      attention: 0
    },
    limit: 50,
    offset: 0
  });
  const v = await workflowView({
    initial: "制造项目",
    readProjects: async () => [oem as any],
    readProject: async () => ({
      ...oem,
      version
    }) as any,
    readMaterialProject: async () => page()
  });
  const original = globalThis.fetch;
  const ref = {
    kind: "mes_component",
    binding_id: "b",
    snapshot_id: "s",
    component_key: "1"
  };
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    const url = String(input);
    if (url.includes("/material-task-references?"))
      return new Response(JSON.stringify({
        project_id: project.id,
        task_kind: "verify",
        project_version: version,
        items: [{
            reference: ref,
            evidence: {
              reference: ref,
              title: "组件甲",
              origin: "mock",
              environment: "test"
            },
            can_open: true,
            existing_task_id: null
          }],
        total: 1
      }));
    if (url.includes("/material-control/assignees?"))
      return new Response(JSON.stringify({
        items: [{
            id: "u",
            display_name: "李工"
          }],
        total: 1
      }));
    if (url.endsWith("/commands"))
      return new Promise<Response>(r => {
        resolve = r;
      });
    return original(input, init);
  }));
  try {
    await v.click("供应与物料");
    await v.click("安排核实");
    await v.click("组件甲");
    await v.field("核实人", "u");
    await v.field("核实任务说明", "原说明");
    await v.click("创建核实任务");
    await v.field("核实任务说明", "更新后的说明");
    version = 4;
    await act(async () => resolve(new Response(JSON.stringify({
      project_id: project.id,
      project_version: 4,
      object_type: "material_task",
      object_id: "t"
    }))));
    await new Promise(r => setTimeout(r, 0));
    expect((v.host.querySelector("[aria-label=\"核实任务说明\"]") as HTMLInputElement).value).toBe("更新后的说明");
    expect(v.host.textContent).toContain("草稿已保留");
  }
  finally {
    await v.dispose();
  }
});
it("opens IQC from a newly matched verification arrival using the exact receipt URL in WorkflowApp", async () => {
  const oem = {
    ...project,
    mode: "oem" as const,
    allowed_actions: ["material_task.open"] as never
  };
  const summary = {
    id: "verify-task",
    project_id: project.id,
    kind: "material_task",
    title: "核对最初包裹",
    state: "processing",
    next_actions: [],
    blocking_reasons: []
  };
  const pinned = {
    kind: "arrival",
    id: "a",
    version: 1
  };
  let arrivalVersion = 1;
  const view = await workflowView({
    initial: "制造项目",
    readProject: async () => oem,
    readProjects: async () => [oem],
    readMaterialTasks: async () => ({
      items: [summary],
      total: 1,
      limit: 50,
      offset: 0
    }) as never,
    readObject: async (_pid, kind, id) => {
      if (kind === "arrival")
        return {
          summary: {
            id: "a",
            project_id: project.id
          },
          value: {
            kind: "arrival",
            id: "a",
            arrival_number: "A",
            location: "库房",
            package_count: 1,
            description: "标签",
            state: arrivalVersion === 1 ? "unlinked" : "matched",
            receipt_id: arrivalVersion === 1 ? null : "exact-receipt",
            matches: arrivalVersion === 1 ? [] : [{
                receipt_id: "exact-receipt"
              }]
          },
        } as never;
      return {
        summary: {
          ...summary,
          id,
          title: id === "existing-iqc" ? "已有检验任务" : summary.title
        },
        value: {
          kind: "material_task",
          task_kind: "verify",
          state: "processing",
          history: [],
          requirement_id: null,
          receipt_id: null,
          handoff_id: null,
          reference: {
            reference: pinned,
            title: "固定初始依据",
            origin: "manual",
            environment: "unknown",
            receipt_id: null
          },
          reference_current: arrivalVersion === 1,
          current_reference: {
            ...pinned,
            version: arrivalVersion
          },
          reference_issue: "Arrival match changed"
        },
      } as never;
    },
  });
  const original = globalThis.fetch;
  const referenceUrls: URL[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    const url = new URL(String(input), "http://local.test");
    if (url.pathname.endsWith("/material-task-references")) {
      referenceUrls.push(url);
      return new Response(JSON.stringify({
        project_id: project.id,
        project_version: 3,
        task_kind: "iqc",
        total: 1,
        items: [{
            reference: {
              kind: "receipt",
              id: "exact-receipt"
            },
            evidence: {
              reference: {
                kind: "receipt",
                id: "exact-receipt"
              },
              receipt_id: "exact-receipt",
              title: "准确收货",
              origin: "manual",
              environment: "unknown"
            },
            can_open: false,
            existing_task_id: "existing-iqc"
          }]
      }));
    }
    if (url.pathname.endsWith("/material-control/assignees"))
      return new Response(JSON.stringify({
        items: []
      }));
    return original(input, init);
  }));
  try {
    await view.click("供应与物料");
    await view.click("核对最初包裹");
    expect(view.host.textContent).not.toContain("为关联收货安排检验");
    await view.click("返回业务列表");
    arrivalVersion = 2;
    await view.click("核对最初包裹");
    expect(view.host.textContent).toContain("固定初始依据");
    await view.click("为关联收货安排检验");
    expect(referenceUrls).toHaveLength(1);
    expect(referenceUrls[0].searchParams.get("receipt_id")).toBe("exact-receipt");
    await view.click("打开已有任务");
    expect(view.requests.some(request => request.url.endsWith("/objects/material_task/existing-iqc"))).toBe(true);
  }
  finally {
    await view.dispose();
  }
});
