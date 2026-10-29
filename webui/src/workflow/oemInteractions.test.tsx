import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CalibrationForms } from "./forms/CalibrationForms";
import { ArrivalForms } from "./forms/ArrivalForms";
import { IntroductionWorkspace } from "./IntroductionWorkspace";
import { LaboratoryWorkspace } from "./LaboratoryWorkspace";
import { UnitPassport } from "./UnitPassport";
import { AssistancePanel } from "./AssistancePanel";
import { workflowView, project, bootstrap, flush } from "./testHelpers";
import type { ObjectSummary, WorkspaceProps, ObjectDetail } from "./types";
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const summary = (kind: string, id: string, title = id) =>
  ({
    kind,
    id,
    title,
    project_id: project.id,
    state: "pending",
    source: null,
    quantity: null,
    unit: null,
    version: 1,
    blocking_reasons: [],
    next_actions: [],
  }) as ObjectSummary;
const noEvidence = {
  items: [],
  unknowns: [],
  state: "no_evidence",
  truncated: false,
};
const api = (): any => ({
  objects: vi.fn(async () => ({ items: [], total: 0 })),
  object: vi.fn(),
  publicAssets: vi.fn(async () => ({ items: [], total: 0 })),
  assistance: vi.fn(async () => noEvidence),
  command: vi.fn(),
});
const props = (client: any): WorkspaceProps => ({
  api: client,
  project,
  onChanged: vi.fn(),
  onOpen: vi.fn(),
  onDirty: vi.fn(),
  readOnly: false,
});
async function choose(name: string, value: string) {
  const e = host.querySelector(`[aria-label="${name}"]`) as HTMLSelectElement;
  expect(e).toBeTruthy();
  await act(async () => {
    e.value = value;
    e.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
it("retires a late calibration selection and never copies its expected values into observed data", async () => {
  const client = api(),
    pending = new Map<string, (value: any) => void>();
  client.object.mockImplementation(
    async (_p: any, _k: any, id: string) =>
      new Promise((r) => pending.set(id, r)),
  );
  await act(async () =>
    root.render(
      <CalibrationForms
        {...props(client)}
        action="calibration.confirm"
        items={{
          calibration: [
            summary("calibration", "a"),
            summary("calibration", "b"),
          ],
        }}
      />,
    ),
  );
  await choose("待确认标定", "a");
  await choose("待确认标定", "b");
  const response = (name: string, value: string) => ({
    value: {
      kind: "calibration",
      origin: "manual",
      parameters: [{ name, value, unit: "ratio" }],
    },
  });
  await act(async () => pending.get("b")!(response("current", "2")));
  await act(async () => pending.get("a")!(response("stale", "999")));
  expect(host.textContent).toContain("current");
  expect(host.textContent).not.toContain("stale");
  expect(
    (host.querySelector('[aria-label="实际读回数值 1"]') as HTMLInputElement)
      .value,
  ).toBe("");
  await act(async () => root.unmount());
  root = createRoot(host);
  expect(client.command).not.toHaveBeenCalled();
});
it("requires correction reason only for an already matched arrival", async () => {
  const client = api();
  client.object.mockResolvedValue({
    value: { kind: "arrival", receipt_id: "receipt-old" },
  });
  await act(async () =>
    root.render(
      <ArrivalForms
        {...props(client)}
        action="arrival.match"
        items={{
          arrival: [summary("arrival", "a")],
          receipt: [summary("receipt", "r")],
        }}
      />,
    ),
  );
  await choose("待匹配收货观察", "a");
  expect(
    (host.querySelector('[aria-label="匹配纠正原因"]') as HTMLInputElement)
      .required,
  ).toBe(true);
});
it("keeps ordinary roles and readonly views scoped while administrators can use all returned actions", async () => {
  const client = api();
  const base = { ...props(client), requestLeave: (f: () => void) => f() };
  await act(async () =>
    root.render(
      <IntroductionWorkspace
        {...base}
        project={{ ...project, allowed_actions: ["npi.issue"] }}
      />,
    ),
  );
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "登记导入问题",
    ),
  ).toBe(true);
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "发布可复用资产",
    ),
  ).toBe(false);
  await act(async () =>
    root.render(
      <LaboratoryWorkspace
        {...base}
        readOnly
        project={{
          ...project,
          allowed_actions: ["test_run.start", "calibration.confirm"],
        }}
      />,
    ),
  );
  expect(host.querySelector("form")).toBeNull();
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "开始测试运行",
    ),
  ).toBe(false);
});
it("keeps new domain drafts through handbook and supports project and global navigation", async () => {
  const p = {
    ...project,
    allowed_actions: [
      "npi.open",
      "test_plan.publish",
    ] as typeof project.allowed_actions,
  };
  const v = await workflowView({
    readProjects: async () => [p],
    readProject: async () => p,
    options: {
      bootstrap: { ...bootstrap, configuration_admin: true },
      renderMarkdown: (element, value) => {
        element.textContent = value.markdown;
        return {
          unmount() {
            element.textContent = "";
          },
        };
      },
    },
  });
  try {
    await v.click("工程与资产");
    await v.field("所属项目筛选", project.id);
    await v.click("进入项目办理");
    await v.click("创建工程导入");
    await v.field("产品族", "draft camera");
    await v.click("制造手册");
    expect(v.host.textContent).toContain("完整连续正文");
    await v.click("返回工作区");
    expect(
      (v.host.querySelector('[aria-label="产品族"]') as HTMLInputElement).value,
    ).toBe("draft camera");
    await v.click("测试与标定");
    expect(v.host.querySelector('[role="dialog"]')).toBeTruthy();
  } finally {
    await v.dispose();
  }
});
it("joins the exact unit id for laboratory passport and exposes bounded coverage", async () => {
  const client = api();
  client.objects.mockImplementation(async (_p: any, kind: string) => ({
    items: [summary(kind, "mine"), summary(kind, "other")],
    total: 51,
  }));
  client.object.mockImplementation(
    async (_p: any, kind: string, id: string) => ({
      summary: summary(kind, kind + id),
      value: { kind, unit_id: id === "mine" ? "unit-one" : "foreign-unit" },
    }),
  );
  const detail = {
    summary: summary("unit", "unit-one"),
    value: {
      kind: "unit",
      sn: "S1",
      aliases: [
        {
          id: "a",
          customer_id: "c",
          customer_serial: "C1",
          evidence: "alias evidence",
          actor_id: "who",
          recorded_at: "when",
        },
      ],
      components: [
        {
          id: "component",
          material_id: "m",
          component_serial: "C",
          origin: "manual",
          state: "removed",
          evidence: "install",
          actor_id: "a",
          recorded_at: "t",
          removal: { evidence: "remove", actor_id: "b", recorded_at: "u" },
        },
      ],
    },
    relations: [],
    evidence: [],
    history: [],
  } as unknown as ObjectDetail;
  await act(async () =>
    root.render(
      <UnitPassport api={client as any} data={detail} onOpen={() => {}} />,
    ),
  );
  await flush();
  expect(host.textContent).toContain("C1");
  expect(host.textContent).toContain("remove");
  expect(host.textContent).toContain("2/51");
  expect(host.textContent).not.toContain("test_runother");
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "继续核对实验室履历",
    ),
  ).toBe(true);
});
it("retires an old lookup page and releases paging controls after the project changes", async () => {
  const client = api();
  let finish!: (page: unknown) => void;
  client.objects.mockImplementation(
    async (pid: string, kind: string, _limit: number, offset: number) => {
      if (pid === project.id && kind === "revision" && offset === 50)
        return new Promise((resolve) => {
          finish = resolve;
        });
      return {
        items:
          kind === "revision"
            ? Array.from({ length: 50 }, (_, i) => summary(kind, `${pid}-${i}`))
            : [],
        total: kind === "revision" ? 51 : 0,
      };
    },
  );
  const base = { ...props(client), requestLeave: (f: () => void) => f() };
  await act(async () => root.render(<IntroductionWorkspace {...base} />));
  const lookup = () =>
    [...host.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("50/51"),
    )!;
  expect(lookup()).toBeTruthy();
  await act(async () => lookup().click());
  await act(async () =>
    root.render(
      <IntroductionWorkspace
        {...base}
        project={{ ...project, id: "new-project" }}
      />,
    ),
  );
  expect(lookup().disabled).toBe(false);
  await act(async () =>
    finish({
      items: [summary("revision", "late", "OLD PRIVATE REVISION")],
      total: 51,
    }),
  );
  expect(host.textContent).not.toContain("OLD PRIVATE REVISION");
});
it("keeps a directly opened record selectable beyond the first lookup page", async () => {
  const client = api();
  const current = {
    summary: summary("npi_issue", "issue-51", "Previously opened issue"),
    value: {
      kind: "npi_issue",
      state: "unverified",
      verified: false,
      resolutions: [],
      resolution: null,
    },
    relations: [],
    evidence: [],
    history: [],
  } as unknown as ObjectDetail;
  await act(async () =>
    root.render(
      <IntroductionWorkspace
        {...props(client)}
        project={{ ...project, allowed_actions: ["npi.resolve"] }}
        requestLeave={(f) => f()}
        initialAction="npi.resolve"
        initialObject={current}
      />,
    ),
  );
  const selected = host.querySelector(
    '[aria-label="待验证问题"]',
  ) as HTMLSelectElement;
  expect(selected.value).toBe("issue-51");
  expect(selected.selectedOptions[0].textContent).toContain(
    "Previously opened issue",
  );
});
it("opens the requested new action after explicitly discarding a dirty domain form", async () => {
  const p = {
    ...project,
    allowed_actions: [
      "npi.open",
      "npi.issue",
    ] as typeof project.allowed_actions,
  };
  const v = await workflowView({
    readProjects: async () => [p],
    readProject: async () => p,
  });
  try {
    await v.click("工程与资产");
    await v.field("所属项目筛选", project.id);
    await v.click("进入项目办理");
    await v.click("创建工程导入");
    await v.field("产品族", "dirty draft");
    await v.click("登记导入问题");
    await v.click("放弃并离开");
    expect(
      v.host.querySelector('form[aria-label="登记导入问题"]'),
    ).toBeTruthy();
    expect(v.host.querySelector('form[aria-label="创建工程导入"]')).toBeNull();
  } finally {
    await v.dispose();
  }
});
it("switches between arrival and existing receiving forms with one active draft", async () => {
  const p = {
    ...project,
    allowed_actions: [
      "supply.receive",
      "arrival.record",
    ] as typeof project.allowed_actions,
  };
  const v = await workflowView({
    readProjects: async () => [p],
    readProject: async () => p,
  });
  try {
    await v.click("计划与物料");
    await v.field("所属项目筛选", project.id);
    await v.click("进入项目办理");
    await v.click("登记到货");
    await v.click("登记收货观察");
    expect(v.host.querySelectorAll("form")).toHaveLength(1);
    await v.field("实物观察描述", "observed packages");
    await v.click("登记到货");
    await v.click("放弃并离开");
    expect(v.host.querySelectorAll("form")).toHaveLength(1);
    expect(v.host.querySelector('form[aria-label="登记到货"]')).toBeTruthy();
  } finally {
    await v.dispose();
  }
});

const passportUnit = {
  summary: summary("unit", "unit-one"),
  value: { kind: "unit", sn: "S1", aliases: [], components: [] },
  relations: [],
  evidence: [],
  history: [],
} as unknown as ObjectDetail;
const passportButton = (text: string) =>
  [...host.querySelectorAll("button")].find(
    (button) => button.textContent === text,
  );

it.each(["request", "detail"])(
  "retries the failed passport calibration %s without skipping its first page",
  async (failure) => {
    const client = api();
    let fail = true;
    client.objects.mockImplementation(
      async (_p: string, kind: string, _limit: number, offset: number) => {
        if (fail && kind === "calibration" && failure === "request")
          throw new Error("calibration request failed");
        return {
          items:
            kind === "test_run"
              ? Array.from({ length: Math.min(25, 51 - offset) }, (_, i) =>
                  summary(kind, `run-${offset + i}`),
                )
              : offset === 0
                ? [summary(kind, "calibration-mine")]
                : [],
          total: kind === "test_run" ? 51 : 1,
        };
      },
    );
    client.object.mockImplementation(
      async (_p: string, kind: string, id: string) => {
        if (fail && kind === "calibration" && failure === "detail")
          throw new Error("calibration detail failed");
        return {
          summary: summary(kind, id),
          value: { kind, unit_id: "unit-one" },
        };
      },
    );
    await act(async () =>
      root.render(
        <UnitPassport api={client} data={passportUnit} onOpen={() => {}} />,
      ),
    );
    expect(host.querySelector('[role="alert"]')).toBeTruthy();
    expect(host.textContent).toContain("运行 25/51");
    expect(passportButton("继续核对实验室履历")).toBeUndefined();
    fail = false;
    await act(async () => passportButton("重试读取履历")!.click());
    expect(host.querySelector('[role="alert"]')).toBeNull();
    expect(host.textContent).toContain("calibration-mine");
    expect(host.textContent).toContain("标定 1/1");
    expect(
      client.objects.mock.calls.every((call: unknown[]) => call[3] === 0),
    ).toBe(true);
    expect(passportButton("继续核对实验室履历")).toBeTruthy();
  },
);

it("does not count or skip unread passport details after a later page fails", async () => {
  const client = api();
  let fail = true;
  client.objects.mockImplementation(
    async (_p: string, kind: string, _limit: number, offset: number) => ({
      items: Array.from({ length: Math.min(25, 51 - offset) }, (_, i) =>
        summary(kind, `${kind}-${offset + i}`),
      ),
      total: 51,
    }),
  );
  client.object.mockImplementation(
    async (_p: string, kind: string, id: string) => {
      if (fail && id === "calibration-26") throw new Error("unread detail");
      return {
        summary: summary(kind, id),
        value: { kind, unit_id: "unit-one" },
      };
    },
  );
  await act(async () =>
    root.render(
      <UnitPassport api={client} data={passportUnit} onOpen={() => {}} />,
    ),
  );
  await act(async () => passportButton("继续核对实验室履历")!.click());
  expect(host.querySelector('[role="alert"]')).toBeTruthy();
  expect(host.textContent).toContain("运行 50/51");
  expect(host.textContent).toContain("标定 25/51");
  expect(host.textContent).not.toContain("calibration-25");
  expect(passportButton("继续核对实验室履历")).toBeUndefined();
  fail = false;
  await act(async () => passportButton("重试读取履历")!.click());
  expect(host.textContent).toContain("标定 50/51");
  expect(host.textContent).toContain("calibration-25");
  await act(async () => passportButton("继续核对实验室履历")!.click());
  expect(host.textContent).toContain("运行 51/51");
  expect(host.textContent).toContain("标定 51/51");
  expect(passportButton("继续核对实验室履历")).toBeUndefined();
});

it("labels a running passport test run as manual registration", async () => {
  const client = api();
  client.objects.mockImplementation(async (_p: string, kind: string) => ({
    items: kind === "test_run" ? [summary(kind, "run")] : [],
    total: kind === "test_run" ? 1 : 0,
  }));
  client.object.mockResolvedValue({
    summary: { ...summary("test_run", "run"), state: "running" },
    value: { kind: "test_run", unit_id: "unit-one" },
  });
  await act(async () =>
    root.render(
      <UnitPassport api={client} data={passportUnit} onOpen={() => {}} />,
    ),
  );
  expect(host.textContent).toContain("运行登记中");
  expect(host.textContent).not.toContain("MES 已确认运行");
});

it("labels assistance run summaries and lifecycle as registration while preserving production MES states", async () => {
  const client = api();
  const item = (kind: string) => ({
    target: { scope: "project", project_id: project.id, kind, id: kind },
    title: kind,
    state: "running",
    suggestion: "Review registered evidence",
    blockers: [],
    unknowns: [],
    evidence: [],
    related_targets: [],
    testing:
      kind === "test_run"
        ? {
            run_state: "running",
            outcome: null,
            current_qualified: null,
            program_version: "P1",
            measurements: [],
            failed_measurements: [],
            similar_targets: [],
          }
        : null,
  });
  client.assistance.mockResolvedValue({
    ...noEvidence,
    state: "evidence_available",
    items: [item("test_run"), item("unit")],
  });
  await act(async () =>
    root.render(
      <AssistancePanel
        api={client}
        projectId={project.id}
        version={1}
        onOpen={() => {}}
        initialKind="testing"
      />,
    ),
  );
  const sections = host.querySelectorAll("details");
  expect(sections).toHaveLength(2);
  expect(sections[0].querySelector("summary")!.textContent).toContain(
    "运行登记中",
  );
  expect(sections[0].textContent).toContain("运行生命周期 运行登记中");
  expect(sections[0].textContent).not.toContain("MES 已确认运行");
  expect(sections[1].querySelector("summary")!.textContent).toContain(
    "MES 已确认运行",
  );
});
