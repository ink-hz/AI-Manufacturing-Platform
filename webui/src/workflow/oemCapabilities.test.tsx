/// <reference types="vite/client" />
import { act, type ComponentType } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DetailContent } from "./WorkflowDetail";
import { businessModules } from "./navigationContext";
import { createWorkflowApi } from "./api";
import type { ObjectDetail, WorkspaceProps } from "./types";
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
const summary = (kind: string) => ({
  id: "object-1",
  project_id: "project-1",
  kind,
  title: "真实记录",
  state: "pass",
  version: 1,
  source: null,
  quantity: null,
  unit: null,
  blocking_reasons: [],
  next_actions: [],
});
async function detail(kind: string, value: unknown) {
  await act(async () =>
    root.render(
      <DetailContent
        data={
          {
            summary: summary(kind),
            value,
            relations: [],
            evidence: [],
            history: [],
          } as ObjectDetail
        }
        onOpen={() => {}}
      />,
    ),
  );
}
it("provides engineering/asset and laboratory ledgers with real registered objects", () => {
  expect(
    (businessModules as any).introduction?.tabs.map((x: any) => x.kind),
  ).toEqual(
    expect.arrayContaining(["npi", "npi_issue", "reusable_asset", "asset_use"]),
  );
  expect(
    (businessModules as any).laboratory?.tabs.map((x: any) => x.kind),
  ).toEqual(
    expect.arrayContaining([
      "test_plan",
      "test_run",
      "calibration",
      "component_link",
    ]),
  );
});
it("separates historical NPI approval from current blocked eligibility and resolution history", async () => {
  await detail("npi", {
    kind: "npi",
    revision_id: "rev",
    product_family: "camera",
    scenario: "first_introduction",
    required_checks: ["drawing"],
    work_order_ids: [],
    state: "approved",
    bulk_eligible: false,
    blocking_reasons: ["new evidence requires approval"],
    reviews: [],
    trials: [],
    approvals: [],
  });
  expect(host.textContent).toContain("当前批量资格");
  expect(host.textContent).toContain("new evidence requires approval");
});
it("renders exact curve evidence units and lifecycle separately from pass verdict", async () => {
  await detail("test_run", {
    kind: "test_run",
    id: "run",
    plan_id: "plan",
    unit_id: "unit",
    revision_id: "rev",
    attempt: 2,
    state: "completed",
    outcome: "pass",
    scope: {
      program_version: "P1",
      test_version: "T1",
      firmware_version: "F1",
      route_fingerprint: "hash",
      equipment_check_id: "eq",
    },
    execution_event_ids: [],
    actor_id: "actor",
    recorded_at: "now",
    raw: {
      origin: "manual",
      logs: ["actual log"],
      curves: [
        {
          name: "current",
          x_unit: "ms",
          y_unit: "mA",
          points: [{ x: "0.00000000000000000001", y: "12.34567890123456789" }],
        },
      ],
    },
    raw_digest: "digest",
    test_id: "test",
    finish: null,
  });
  expect(host.textContent).toContain("运行生命周期");
  expect(host.textContent).toContain("历史判定");
  expect(host.textContent).toContain("12.34567890123456789");
  expect(host.querySelector("svg")).toBeTruthy();
  expect(host.textContent).toContain("mA");
});
it("exposes catalog and all rule modes using the retiring authenticated API", async () => {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requests.push(url);
      return new Response(JSON.stringify({ items: [] }));
    }),
  );
  const api = createWorkflowApi({
    apiBase: "/api/v1/manufacturing",
    csrfToken: "token",
    readOnly: false,
  });
  expect(typeof (api as any).publicAssets).toBe("function");
  expect(typeof (api as any).assistance).toBe("function");
  await (api as any).publicAssets();
  await (api as any).assistance("project-1", "testing");
  expect(requests).toContain(
    "/api/v1/manufacturing/workflow/projects/project-1/assistance?kind=testing",
  );
  api.dispose();
  await expect((api as any).assistance("project-1", "quality")).rejects.toThrow(
    "retired",
  );
});
const modules = import.meta.glob("./forms/*Forms.tsx");
const actions = {
  IntroductionForms: [
    "npi.open",
    "npi.review",
    "npi.trial",
    "npi.issue",
    "npi.resolve",
    "npi.approve",
  ],
  AssetForms: ["asset.publish", "asset.apply", "asset.verify"],
  LaboratoryForms: ["test_plan.publish", "test_run.start", "test_run.finish"],
  CalibrationForms: ["calibration.record", "calibration.confirm"],
  GenealogyForms: ["unit.alias", "component.install", "component.remove"],
  ArrivalForms: ["arrival.record", "arrival.match"],
  AuthorityForms: ["authority.register", "authority.verify"],
};
for (const [name, commands] of Object.entries(actions))
  it(`renders every named ${name} command as an operable form`, async () => {
    const loader = modules[`./forms/${name}.tsx`];
    expect(loader, `${name} is required`).toBeDefined();
    const Component = (await loader()) as Record<string, ComponentType<any>>;
    const props = {
      project: { id: "project-1", version: 3, allowed_actions: commands },
      api: {
        objects: async () => ({ items: [], total: 0 }),
        object: async () => ({}),
        publicAssets: async () => ({ items: [], total: 0 }),
      },
      readOnly: false,
      onDirty: () => {},
      onChanged: () => {},
      onOpen: () => {},
      items: {},
      configurationAdmin: true,
    } as unknown as WorkspaceProps;
    for (const action of commands) {
      await act(async () =>
        root.render(
          <ComponentView
            key={action}
            component={Component[name]}
            props={{ ...props, action }}
          />,
        ),
      );
      expect(host.querySelector("form[aria-label]"), action).toBeTruthy();
      expect(host.querySelector('button[type="submit"]'), action).toBeTruthy();
      expect(host.querySelector('textarea[aria-label*="JSON"]')).toBeNull();
    }
  });
function ComponentView({
  component: C,
  props,
}: {
  component: ComponentType<any>;
  props: any;
}) {
  return <C {...props} />;
}
const workspaceModules = import.meta.glob("./*.tsx");
it("offers all six rule modes and opens public evidence without protected project requests", async () => {
  const load = workspaceModules["./AssistancePanel.tsx"];
  expect(load).toBeDefined();
  const { AssistancePanel } = (await load()) as any;
  const onOpen = vi.fn();
  const requested: string[] = [];
  const api = {
    assistance: async (_id: string, kind: string) => {
      requested.push(kind);
      return {
        mode: "rules",
        kind,
        state: "evidence_available",
        unknowns: ["outside evidence unknown"],
        truncated: true,
        items: [
          {
            target: {
              scope: "public_catalog",
              project_id: null,
              kind: "reusable_asset",
              id: "public-1",
            },
            title: "generic check",
            state: "published",
            suggestion: "Review applicability",
            blockers: [],
            unknowns: ["target verification needed"],
            evidence: ["approved public"],
            related_targets: [],
            public_asset: {
              asset_revision_id: "public-1",
              revision: 2,
              content: {
                title: "generic check",
                category: "check",
                product_families: ["camera"],
                execution_content: "public execution",
                verification_method: "public inspection",
              },
            },
            evidence_truncated: false,
          },
        ],
      };
    },
  };
  await act(async () =>
    root.render(
      <AssistancePanel api={api} projectId="p" version={1} onOpen={onOpen} />,
    ),
  );
  expect(requested).toEqual([]);
  await act(async () => (host.querySelector('button[aria-expanded="false"]') as HTMLButtonElement).click());
  const select = host.querySelector("select")!;
  expect([...select.options].map((o) => o.value)).toEqual([
    "introduction",
    "materials",
    "change",
    "knowledge",
    "testing",
    "quality",
  ]);
  for (const mode of ["materials", "change", "knowledge", "testing", "quality"])
    await act(async () => {
      select.value = mode;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
  expect(requested).toEqual([
    "introduction",
    "materials",
    "change",
    "knowledge",
    "testing",
    "quality",
  ]);
  const b = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "查看公共内容",
  );
  expect(b).toBeTruthy();
  await act(async () => b!.click());
  expect(host.textContent).toContain("public execution");
  expect(onOpen).not.toHaveBeenCalled();
  expect(host.textContent).toContain("核对建议");
  expect(host.textContent).toContain("有界");
});
it("keeps calibration expected values out of observed readback inputs", async () => {
  const load = modules["./forms/CalibrationForms.tsx"];
  expect(load).toBeDefined();
  const { CalibrationForms } = (await load()) as any;
  const api = {
    object: async () => ({
      summary: summary("calibration"),
      value: {
        kind: "calibration",
        origin: "manual",
        parameters: [{ name: "gain", value: "1.25", unit: "ratio" }],
      },
    }),
    command: vi.fn(),
  };
  await act(async () =>
    root.render(
      <CalibrationForms
        api={api}
        project={{ id: "p", version: 1 }}
        items={{ calibration: [{ ...summary("calibration"), id: "cal" }] }}
        action="calibration.confirm"
        onDirty={() => {}}
        onChanged={() => {}}
        onOpen={() => {}}
      />,
    ),
  );
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "cal";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("1.25");
  expect(
    (host.querySelector('[aria-label="实际读回数值 1"]') as HTMLInputElement)
      .value,
  ).toBe("");
});
it("shows current linked quality qualification independently of a historical passing run", async () => {
  const run = {
    summary: { ...summary("test_run"), state: "pass" },
    value: {
      kind: "test_run",
      id: "run",
      plan_id: "plan",
      unit_id: "unit",
      revision_id: "rev",
      attempt: 1,
      state: "completed",
      outcome: "pass",
      scope: {
        program_version: "P1",
        test_version: "T1",
        firmware_version: "F1",
        route_fingerprint: "hash",
        equipment_check_id: "eq",
      },
      execution_event_ids: [],
      actor_id: "actor",
      recorded_at: "now",
      raw: null,
      test_id: "quality-test",
      finish: null,
    },
    relations: [],
    evidence: [],
    history: [],
  } as unknown as ObjectDetail;
  const client = {
    object: vi.fn(async () => ({
      value: {
        kind: "test",
        current_qualified: false,
        current_blocking_reasons: ["later failed retest"],
      },
    })),
  };
  await act(async () =>
    root.render(
      <DetailContent data={run} api={client as any} onOpen={() => {}} />,
    ),
  );
  expect(host.textContent).toContain("历史判定");
  expect(host.textContent).toContain("later failed retest");
  expect(host.textContent).toContain("当前测试资格：无效");
});
