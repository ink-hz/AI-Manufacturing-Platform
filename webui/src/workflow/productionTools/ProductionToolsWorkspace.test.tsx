import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { createWorkflowApi } from "../api";
import { flush } from "../testHelpers";
import { ProductionToolsWorkspace } from "./ProductionToolsWorkspace";
import { localInput } from "./context";
const project = { id: "99999999999999999999", name: "项目 A" },
  other = { id: "9007199254740993", name: "项目 B" };
const now = "2026-11-10T08:00:00Z",
  snap = "11111111-1111-4111-8111-111111111111",
  draftId = "22222222-2222-4222-8222-222222222222",
  handoffId = "33333333-3333-4333-8333-333333333333";
const range = { start: "2026-11-10T00:00:00Z", end: now };
const fail = {
  timestamp: "2026-11-10T06:00:00Z",
  sn: "SN-A",
  status: "2",
  workstagesid: "7",
  softwareid: "8",
  version: "v2",
  configlogsid: "9",
  cversion: "c2",
  devicename: "PC07",
  errorcode: "E1",
  orderid: "19",
  measurement: 12,
};
const pass = {
  ...fail,
  timestamp: "2026-11-10T05:00:00Z",
  status: "1",
  devicename: "PC01",
  softwareid: "18",
  errorcode: null,
  measurement: 10,
};
const comparisonPass = {
  ...pass,
  softwareid: "8",
  version: "v1",
  cversion: "c1",
};
const sourceRow = (offset: number) =>
  offset === 0 ? fail : offset === 1 ? comparisonPass : pass;
const aggregate = {
  key: "[]",
  records: "100",
  distinct_sn: "80",
  pass_records: "80",
  fail_records: "15",
  unknown_records: "5",
  failed_sn: "12",
  first_time: range.start,
  last_time: now,
  denominator_records: "100",
};
const block = {
  state: "ready",
  captured_at: now,
  complete: true,
  truncation_reason: null,
  error: null,
};
const status = {
  configured: true,
  source_namespace: "native",
  source_project_id: null,
  capabilities: Object.fromEntries(
    [
      "production",
      "stopover",
      "software",
      "configs",
      "software_versions",
      "config_versions",
      "review_orders",
      "evidence",
      "evidence_content",
    ].map((k) => [k, { available: true, reason: null }]),
  ),
};
const page = (items: object[], extra = {}) => ({
  snapshot_id: snap,
  source_namespace: "native",
  source_project_id: project.id,
  source_kind: "production",
  captured_at: now,
  expires_at: "2026-11-11T08:00:00Z",
  items,
  filters: range,
  complete: true,
  truncation_reason: null,
  next_before_id: null,
  redacted_fields: [],
  offset: 0,
  limit: 50,
  captured_count: items.length,
  has_more: false,
  ...extra,
});
const selection = (offset: number) => ({
  selection_id: `44444444-4444-4444-8444-${String(offset).padStart(12, "0")}`,
  snapshot_id: snap,
  offset,
  descriptor: Object.fromEntries(
    Object.entries(sourceRow(offset)).filter(([key]) => key !== "measurement"),
  ),
  fingerprint: "hash",
  source_kind: "production",
});
const initialDraft = () => ({
  id: draftId,
  source_namespace: "native",
  source_project_id: project.id,
  owner_id: "admin-A",
  version: 1,
  created_at: now,
  updated_at: now,
  expires_at: "2026-12-10T08:00:00Z",
  context: { ...range, view: "anomalies" },
  primary: null,
  comparison: null,
  logs: [],
  note: "",
  impact: null,
});
type Intercept = (
  url: URL,
  init?: RequestInit,
) => Response | Promise<Response> | undefined;
async function view(
  intercept: Intercept = () => undefined,
  props: Record<string, unknown> = {},
) {
  const requests: { url: URL; init?: RequestInit }[] = [];
  let saved: any = initialDraft();
  let handed: any = null;
  const drafts = new Map<string, any>();
  const bind = (d: any, kind: "draft" | "handoff") => ({
    kind,
    id: d.id,
    version: d.version,
    primary_selection_id: d.primary?.selection_id ?? null,
    comparison_selection_id: d.comparison?.selection_id ?? null,
  });
  async function intercepted(url: URL, response: Response) {
    if (!response.ok) return response;
    const data = await response.clone().json();
    if (url.pathname.endsWith("/resolve") && !("binding" in data))
      return new Response(
        JSON.stringify({
          ...data,
          binding: bind(
            url.pathname.includes("/handoffs/")
              ? handed || {
                  ...saved,
                  id: handoffId,
                  primary: selection(0),
                  comparison: selection(1),
                }
              : saved,
            url.pathname.includes("/handoffs/") ? "handoff" : "draft",
          ),
        }),
      );
    if (data?.id && data?.context) {
      if (url.pathname.includes("/handoffs/")) handed = data;
      else {
        saved = data;
        drafts.set(data.source_project_id, data);
      }
    }
    return response;
  }

  const response = (data: unknown) => new Response(JSON.stringify(data));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input, init) => {
      const url = new URL(String(input), location.origin);
      requests.push({ url, init });
      const override = intercept(url, init);
      if (override) return intercepted(url, await override);
      const path = url.pathname,
        body = init?.body ? JSON.parse(String(init.body)) : {};
      if (path.endsWith("/status")) return response(status);
      if (path.endsWith("/production-tools/projects"))
        return response({
          items: [project, other],
          has_more: false,
          next_before_id: null,
        });
      if (path.endsWith("/overview"))
        return response({
          source_namespace: "native",
          captured_at: now,
          complete: true,
          items: [project, other].map((p) => ({
            ...p,
            state: "ready",
            statistics: aggregate,
            trend: [{ ...aggregate, timestamp: range.start }],
            latest_at: now,
            blocks: { statistics: block, trend: block, latest: block },
          })),
          has_more: false,
          next_before_id: null,
        });
      if (path.endsWith("/analysis"))
        return response({
          source_namespace: "native",
          source_project_id: project.id,
          captured_at: now,
          complete: true,
          bucket_minutes: 5,
          filters: Object.fromEntries(url.searchParams),
          items: [
            {
              ...aggregate,
              stage_id: "7",
              stage_name: "无线测试",
              software_id: "8",
              software_name: "无线工具",
              error_code: "E1",
              device: "PC07",
              software_version: "v2",
              config_log_id: "9",
              config_version: "c2",
              timestamp: range.start,
            },
          ],
        });
      if (path.endsWith("/resolve")) {
        const d = path.includes("/handoffs/") ? handed : saved;
        return response({
          binding: bind(d, path.includes("/handoffs/") ? "handoff" : "draft"),
          captured_at: now,
          primary: d.primary
            ? {
                state: "verified",
                descriptor: d.primary.descriptor,
                complete: true,
                candidates: [
                  {
                    snapshot_id: snap,
                    offset: d.primary.offset,
                    row: sourceRow(d.primary.offset),
                  },
                ],
              }
            : null,
          comparison: d.comparison
            ? {
                state: "verified",
                descriptor: d.comparison.descriptor,
                complete: true,
                candidates: [
                  {
                    snapshot_id: snap,
                    offset: d.comparison.offset,
                    row: sourceRow(d.comparison.offset),
                  },
                ],
              }
            : null,
          logs: [],
        });
      }
      if (path.endsWith("/fork"))
        return response({
          ...saved,
          id: draftId,
          origin_handoff_id: handoffId,
        });
      if (path.endsWith("/handoffs") && init?.method === "POST") {
        handed = structuredClone({
          ...saved,
          id: handoffId,
          investigation_id: saved.id,
        });
        return response(handed);
      }
      if (path.includes("/handoffs/")) {
        handed = {
          ...saved,
          id: handoffId,
          investigation_id: draftId,
          primary: selection(0),
          comparison: selection(1),
          note: "交接时的待确认事项",
        };
        return response(handed);
      }
      const sourceProject = path.match(
        /projects\/([0-9]+)\/investigations/,
      )?.[1];
      const currentDraft = sourceProject
        ? drafts.get(sourceProject)
        : undefined;
      if (sourceProject && currentDraft) saved = currentDraft;
      if (init?.method === "PUT" && body.expected_version !== saved.version)
        return new Response(JSON.stringify({ code: "VERSION_CONFLICT" }), {
          status: 409,
        });
      const context = body.context || saved.context;
      const mapping: Record<string, string> = {
        stage_id: "workstagesid",
        software_id: "softwareid",
        status: "status",
        error_code: "errorcode",
        device: "devicename",
        sn: "sn",
        software_version: "version",
        config_version: "cversion",
        config_log_id: "configlogsid",
      };
      for (const which of ["primary", "comparison"])
        if (body[which]) {
          const row = sourceRow(body[which].offset) as Record<string, unknown>;
          for (const [key, native] of Object.entries(mapping)) {
            if (
              which === "comparison" &&
              !["stage_id", "software_id"].includes(key)
            )
              continue;
            if (
              context[key] != null &&
              row[native] != null &&
              String(context[key]) !== String(row[native])
            )
              return new Response(
                JSON.stringify({ code: "SOURCE_INVALID_QUERY" }),
                { status: 422 },
              );
          }
        }
      if (path.endsWith("/investigations")) {
        if (init?.method === "POST") {
          saved = {
            ...initialDraft(),
            ...body,
            source_project_id: sourceProject,
            primary: body.primary ? selection(body.primary.offset) : null,
          };
          drafts.set(sourceProject!, saved);
          return response(saved);
        }
        return response({
          items: currentDraft ? [currentDraft] : [],
          has_more: false,
        });
      }
      if (path.includes("/investigations/")) {
        if (init?.method === "PUT") {
          saved = { ...saved, ...body, version: saved.version + 1 };
          if ("primary" in body) {
            saved.primary = body.primary
              ? selection(body.primary.offset)
              : null;
            saved.comparison = null;
            saved.logs = [];
          }
          if (body.comparison)
            saved.comparison = selection(body.comparison.offset);
          if (body.logs)
            saved.logs = body.logs.map(
              (id: string | { source_log_id: string }) => ({
                source_log_id: typeof id === "string" ? id : id.source_log_id,
                state: "unverified",
                descriptor: { csn: "OTHER-CSN" },
              }),
            );
        }
        drafts.set(sourceProject!, saved);
        return response(saved);
      }
      if (path.endsWith("/evidence"))
        return response(
          page(
            [
              {
                id: "99999999999999999999",
                csn: "OTHER-CSN",
                toolsname: "无线工具",
                devicename: "PC07",
                orderid: "19",
                createtime: now,
              },
            ],
            { source_kind: "evidence" },
          ),
        );
      if (path.includes("/catalog/"))
        return response(
          page([
            { id: "99999999999999999999", name: "无线工具", versions: "v2" },
          ]),
        );
      if (path.includes("/snapshots/"))
        return response(page([pass], { offset: 50 }));
      if (path.endsWith("/observations"))
        return response(
          page(
            url.searchParams.get("kind") === "stopover"
              ? []
              : url.searchParams.get("sn")
                ? [fail, comparisonPass, pass]
                : [fail],
          ),
        );
      return response({});
    }),
  );
  const api = createWorkflowApi({
      apiBase: "/api/v1/manufacturing",
      csrfToken: "csrf",
      readOnly: false,
    }),
    host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <ProductionToolsWorkspace
        api={api}
        userId="admin-A"
        readOnly={false}
        {...props}
      />,
    ),
  );
  await flush();
  const click = async (label: string) => {
    const b = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === label || b.getAttribute("aria-label") === label,
    );
    expect(b, label).toBeTruthy();
    await act(async () => b!.click());
    await flush();
  };
  const field = async (label: string, value: string) => {
    const e = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
    expect(e, label).toBeTruthy();
    await act(async () => {
      const proto =
        e.tagName === "SELECT"
          ? HTMLSelectElement.prototype
          : e.tagName === "TEXTAREA"
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(e, value);
      e.dispatchEvent(new Event("input", { bubbles: true }));
      e.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flush();
  };
  return {
    host,
    requests,
    click,
    field,
    saved: () => saved,
    handed: () => handed,
    dispose: async () => {
      await act(async () => root.unmount());
      api.dispose();
      host.remove();
    },
  };
}
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  history.replaceState(null, "", "/");
});
it("starts with compact controls and opens investigation recovery before focusing it", async () => {
  const v = await view();
  try {
    expect(v.host.querySelector("h2")).toBeNull();
    expect(v.host.querySelector('[aria-label="当前调查"]')).toBeNull();
    expect(v.host.querySelector("textarea")).toBeNull();
    expect(v.host.textContent).not.toContain("生产数据 · 问题定位与调查");
    expect(v.host.textContent).not.toContain("外部产测源只读");
    expect(v.host.textContent).not.toContain("按源项目与问题时段核对数据");
    expect(v.host.textContent).not.toContain("查看截至");
    expect(v.host.querySelector('[aria-label="交接号或内部恢复链接"]')).toBeNull();
    await v.click("恢复调查");
    const input = v.host.querySelector('[aria-label="交接号或内部恢复链接"]');
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);
    await v.field("交接号或内部恢复链接", "invalid");
    await v.click("读取交接");
    expect(v.host.querySelector('[aria-label="当前调查"]')?.textContent).toContain("请输入有效交接号");
  } finally {
    await v.dispose();
  }
});
it("keeps a failed linked restore visible without an explicit panel open", async () => {
  const v = await view((u) => u.pathname.endsWith("/handoffs/" + handoffId)
    ? new Response("{}", { status: 410 }) : undefined, { handoffId });
  try {
    expect(v.host.querySelector('[aria-label="当前调查"]')?.textContent).toContain("已过期");
    expect(v.host.querySelector('[aria-label="交接号或内部恢复链接"]')).not.toBeNull();
  } finally {
    await v.dispose();
  }
});
for (const task of ["anomalies", "activity", "catalog"] as const) {
  it(`preserves the ${task} task when selecting and clearing source projects`, async () => {
    const v = await view();
    const label = task === "anomalies" ? "失败分析" : task === "activity" ? "现场上位机" : "版本使用";
    try {
      await v.click(label);
      expect(v.host.textContent).not.toContain("不逐项目扫描 SN");
      await v.field("源项目", project.id);
      expect(v.host.querySelector('[aria-label="产测主导航"] [aria-pressed="true"]')?.textContent).toBe(label);
      expect(v.requests.some((r) => r.url.pathname.endsWith("/analysis") && r.url.searchParams.get("view") === (task === "anomalies" ? "errors" : task === "activity" ? "devices" : "versions"))).toBe(true);
      await v.field("源项目", "");
      expect(v.host.querySelector('[aria-label="产测主导航"] [aria-pressed="true"]')?.textContent).toBe(label);
    } finally {
      await v.dispose();
    }
  });
}
it("round-trips exact query seconds and milliseconds through local time controls", async () => {
  const exact = { start: "2026-11-10T01:40:59.123Z", end: "2026-11-10T02:50:31.456Z" };
  expect(new Date(localInput(exact.start)).toISOString()).toBe(exact.start);
  const v = await view((u) => u.pathname.endsWith("/handoffs/" + handoffId)
    ? new Response(JSON.stringify({ ...initialDraft(), id: handoffId, context: { ...exact, view: "anomalies" } })) : undefined, { handoffId });
  try {
    for (const [label, value] of [["开始时间", exact.start], ["结束时间", exact.end]]) {
      const input = v.host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
      expect(input.step).toBe("0.001");
      expect(input.validity.stepMismatch).toBe(false);
      expect(new Date(input.value).toISOString()).toBe(value);
    }
    await v.click("应用时间范围");
    const query = v.requests.filter((r) => r.url.pathname.endsWith("/analysis")).at(-1)!.url;
    expect(query.searchParams.get("start")).toBe(exact.start);
    expect(query.searchParams.get("end")).toBe(exact.end);
    expect(v.handed().context).toMatchObject(exact);
  } finally {
    await v.dispose();
  }
});
it("preserves exact captured log bounds in editable candidate controls", async () => {
  const exact = { start: "2026-11-10T01:40:59.123Z", end: "2026-11-10T02:50:31.456Z" };
  const v = await view((u) => u.pathname.endsWith("/handoffs/" + handoffId)
    ? new Response(JSON.stringify({ ...initialDraft(), id: handoffId, primary: selection(0), context: { ...range, view: "anomalies", evidence_range: exact } })) : undefined, { handoffId });
  try {
    await v.click("核对主要候选 1");
    await v.click("查找候选日志");
    for (const [label, value] of [["日志开始时间", exact.start], ["日志结束时间", exact.end]]) {
      const input = v.host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
      expect(input.step).toBe("0.001");
      expect(input.validity.stepMismatch).toBe(false);
      expect(new Date(input.value).toISOString()).toBe(value);
    }
    await v.click("查找日志");
    const query = v.requests.filter((r) => r.url.pathname.endsWith("/evidence")).at(-1)!.url;
    expect(query.searchParams.get("start")).toBe(exact.start);
    expect(query.searchParams.get("end")).toBe(exact.end);
    expect(v.handed().context.evidence_range).toEqual(exact);
  } finally {
    await v.dispose();
  }
});
it("explains project and stage before records, then expands SN beyond symptom filters", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    expect(v.host.textContent).toContain("测试环节");
    expect(
      v.requests.some((r) => r.url.pathname.endsWith("/observations")),
    ).toBe(false);
    await v.click("选择无线测试 · 无线工具");
    const start = v.requests
      .find((r) => r.url.searchParams.get("view") === "stages")!
      .url.searchParams.get("start");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("查看 SN-A 履历");
    expect(v.host.textContent).toContain("通过 PASS");
    const qs = v.requests.filter(
      (r) =>
        r.url.pathname.endsWith("/observations") &&
        r.url.searchParams.has("sn"),
    );
    expect(qs).toHaveLength(2);
    for (const q of qs) {
      expect(q.url.searchParams.get("start")).toBe(start);
      for (const k of [
        "status",
        "device",
        "software_id",
        "stage_id",
        "error_code",
        "missing_fields",
      ])
        expect(q.url.searchParams.has(k)).toBe(false);
    }
    await v.click("返回");
    expect(v.host.textContent).toContain("错误码：E1");
  } finally {
    await v.dispose();
  }
});
it("preserves problem time while comparing explicit recent thirty minutes", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("现场上位机");
    await v.click("查看上位机 PC07");
    const original = v.requests
      .filter((r) => r.url.searchParams.get("view") === "activity")
      .at(-1)!
      .url.searchParams.get("start");
    await v.click("查看近况");
    expect(v.host.textContent).toContain("问题当时");
    expect(v.host.textContent).toContain("最近 30 分钟");
    const recent = v.requests
      .filter((r) => r.url.searchParams.get("view") === "activity")
      .at(-1)!.url;
    expect(
      new Date(recent.searchParams.get("end")!).getTime() -
        new Date(recent.searchParams.get("start")!).getTime(),
    ).toBe(1800000);
    await v.click("查看该时段测试");
    expect(
      v.requests
        .filter((r) => r.url.pathname.endsWith("/observations"))
        .at(-1)!
        .url.searchParams.get("start"),
    ).toBe(original);
  } finally {
    await v.dispose();
  }
});
it("explicitly saves one main, comparison and exact log references without inferring CSN", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查看 SN-A 履历");
    await v.click("查看测试 2");
    await v.click("选作对照");
    expect(v.saved().primary.offset).toBe(0);
    expect(v.saved().comparison.offset).toBe(1);
    await v.click("查找候选日志");
    expect(
      v.requests
        .filter((r) => r.url.pathname.endsWith("/evidence"))
        .at(-1)!
        .url.searchParams.has("sn"),
    ).toBe(false);
    await v.click("加入调查 99999999999999999999");
    expect(v.saved().logs[0].source_log_id).toBe("99999999999999999999");
    await v.field("观察事实和待确认事项", "核对工具");
    await v.click("生成交接摘要");
    expect(v.saved().note).toBe("核对工具");
    expect(v.host.textContent).toContain("复制交接摘要与恢复链接");
  } finally {
    await v.dispose();
  }
});
it("restores metadata despite directory outage, resolves candidates and forks", async () => {
  const v = await view(
    (url) =>
      url.pathname.endsWith("/production-tools/projects")
        ? new Response("{}", { status: 503 })
        : url.pathname.endsWith("/resolve")
          ? new Response(
              JSON.stringify({
                captured_at: now,
                primary: {
                  state: "ambiguous",
                  complete: true,
                  candidates: [
                    { snapshot_id: snap, offset: 0, row: fail },
                    { snapshot_id: snap, offset: 1, row: fail },
                  ],
                },
                comparison: {
                  state: "not_found",
                  complete: true,
                  candidates: [],
                },
                logs: [],
              }),
            )
          : undefined,
    { handoffId },
  );
  try {
    expect(v.host.textContent).toContain("交接时的待确认事项");
    expect(v.host.textContent).toContain("事件待核对：多条候选");
    expect(v.host.textContent).toContain("未找到");
    await v.click("另存为我的调查");
    expect(v.requests.some((r) => r.url.pathname.endsWith("/fork"))).toBe(true);
  } finally {
    await v.dispose();
  }
});
it("failed save blocks handoff and conflicts preserve local notes", async () => {
  let conflict = false;
  const v = await view((url, init) =>
    url.pathname.includes("/investigations/") && init?.method === "PUT"
      ? new Response(
          JSON.stringify({
            code: conflict ? "INVESTIGATION_CONFLICT" : "STORE_UNAVAILABLE",
          }),
          { status: conflict ? 409 : 503 },
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("开始调查");
    await v.field("观察事实和待确认事项", "本机修改");
    await v.click("生成交接摘要");
    expect(v.host.textContent).toContain("保存失败");
    expect(v.requests.some((r) => r.url.pathname.endsWith("/handoffs"))).toBe(
      false,
    );
    conflict = true;
    await v.click("重试保存");
    expect(v.host.textContent).toContain("修订冲突");
    expect(
      (v.host.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("本机修改");
  } finally {
    await v.dispose();
  }
});
it("cancels project reads even when transport ignores abort", async () => {
  let finish!: (r: Response) => void;
  let signal: AbortSignal | null | undefined;
  const v = await view((url, init) =>
    url.pathname.endsWith("/observations") && url.pathname.includes(project.id)
      ? new Promise((r) => {
          finish = r;
          signal = init?.signal;
        })
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.field("源项目", other.id);
    expect(signal?.aborted).toBe(true);
    await act(async () =>
      finish(new Response(JSON.stringify(page([{ sn: "PRIVATE-OLD" }])))),
    );
    await flush();
    expect(v.host.textContent).not.toContain("PRIVATE-OLD");
  } finally {
    await v.dispose();
  }
});
it("catalog clicks keep twenty digit identifiers without parent-ID input", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("工具与配置");
    await v.click("查看无线工具版本");
    expect(v.requests.at(-1)!.url.searchParams.get("parent_id")).toBe(
      project.id,
    );
    expect(v.host.querySelector('[aria-label="父记录 ID"]')).toBeNull();
  } finally {
    await v.dispose();
  }
});
it("preserves nullable scopes and independent overview block states", async () => {
  const v = await view((url) =>
    url.pathname.endsWith("/overview")
      ? new Response(
          JSON.stringify({
            captured_at: now,
            complete: false,
            items: [
              {
                ...project,
                statistics: aggregate,
                trend: [],
                latest_at: null,
                blocks: {
                  statistics: block,
                  trend: { ...block, state: "unavailable", complete: false },
                  latest: { ...block, state: "unavailable", complete: false },
                },
              },
            ],
          }),
        )
      : url.searchParams.get("view") === "errors"
        ? new Response(
            JSON.stringify({
              captured_at: now,
              complete: true,
              items: [
                {
                  ...aggregate,
                  stage_id: null,
                  software_id: null,
                  error_code: null,
                },
              ],
            }),
          )
        : undefined,
  );
  try {
    expect(v.host.textContent).toContain("失败 SN 12");
    expect(v.host.querySelector('.pt-coverage[data-complete="false"]')?.textContent).toContain("部分数据未取得");
    expect(v.host.querySelector(".pt-project-table tbody tr")?.textContent).toContain("未取得");
    expect(v.host.querySelector(".pt-chart svg")).toBeNull();
    await v.click("项目 A");
    await v.click("查看该范围失败");
    await v.click("选择异常 源未提供错误码");
    expect(
      v.requests
        .filter((r) => r.url.pathname.endsWith("/observations"))
        .at(-1)!
        .url.searchParams.get("missing_fields"),
    ).toBe("stage_id,software_id,error_code");
    expect(v.host.textContent).toContain("阶段：源未提供");
  } finally {
    await v.dispose();
  }
});
it("read-only admin restores but cannot save, fork or generate", async () => {
  const v = await view(undefined, {
    readOnly: true,
    userId: "readonly",
    handoffId,
  });
  try {
    expect(v.host.textContent).toContain("交接时的待确认事项");
    for (const label of ["开始调查", "另存为我的调查", "生成交接摘要"])
      expect(
        [...v.host.querySelectorAll("button")].find(
          (b) => b.textContent === label || b.getAttribute("aria-label") === label,
        )?.disabled,
      ).toBe(true);
    expect(v.requests.every((r) => r.init?.method === "GET")).toBe(true);
  } finally {
    await v.dispose();
  }
});
it("keeps original investigation time and persists subsidiary recent scope", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("开始调查");
    const original = v.saved().context.start;
    await v.click("现场上位机");
    await v.click("查看上位机 PC07");
    await v.click("查看近况");
    await v.click("生成交接摘要");
    expect(v.saved().context.start).toBe(original);
    expect(v.saved().context.recent_range).toBeDefined();
    expect(
      +new Date(v.saved().context.recent_range.end) -
        +new Date(v.saved().context.recent_range.start),
    ).toBe(1800000);
  } finally {
    await v.dispose();
  }
});
it("restores main and comparison through project detach and remount without trusting metadata as raw parameters", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查看 SN-A 履历");
    await v.click("查看测试 2");
    await v.click("选作对照");
    await v.click("关闭测试详情");
    await v.field("源项目", other.id);
    await v.field("源项目", project.id);
    expect(v.host.textContent).toContain(draftId);
    expect(v.saved().comparison.offset).toBe(1);
    expect(v.requests.some((r) => r.url.pathname.endsWith("/resolve"))).toBe(
      true,
    );
  } finally {
    await v.dispose();
  }
  const next = await view((url) =>
    url.pathname.endsWith("/" + draftId)
      ? new Response(
          JSON.stringify({
            ...initialDraft(),
            primary: selection(0),
            comparison: selection(1),
          }),
        )
      : url.pathname.endsWith("/resolve")
        ? new Response(
            JSON.stringify({
              captured_at: now,
              primary: {
                state: "unavailable",
                complete: false,
                candidates: [],
              },
              comparison: {
                state: "not_found",
                complete: true,
                candidates: [],
              },
              logs: [],
            }),
          )
        : undefined,
  );
  try {
    expect(next.host.textContent).toContain(draftId);
    await next.click("比较已选记录");
    expect(next.host.textContent).toContain("主要事件和对照参数尚未核对");
    expect(next.host.textContent).not.toContain("measurement");
  } finally {
    await next.dispose();
  }
});
it("preserves snapshot paging absolute offsets and history duplicate rows", async () => {
  const v = await view((url) =>
    url.pathname.endsWith("/observations")
      ? new Response(
          JSON.stringify(
            page([fail, fail], {
              has_more: true,
              captured_count: 100,
              complete: false,
            }),
          ),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查记录");
    expect(v.host.textContent).toContain("仅显示部分记录");
    expect(v.host.textContent).toContain("同时间多条记录，先后未确定");
    await v.click("下一页快照");
    await v.click("查看测试 51");
    await v.click("设为调查对象");
    expect(
      v.requests.find(
        (r) =>
          r.init?.method === "POST" &&
          r.url.pathname.endsWith("/investigations"),
      )?.init?.body,
    ).toContain('"offset":50');
    await v.click("关闭测试详情");
    await v.click("查看 SN-A 履历");
    await v.click("下一页快照");
    expect(v.requests.at(-1)!.url.pathname).toContain("/snapshots/");
  } finally {
    await v.dispose();
  }
});
it("rejects invalid ranges and never queries an unconfigured source", async () => {
  const v = await view();
  try {
    await v.field("开始时间", "2026-09-01T00:00");
    await v.field("结束时间", "2026-11-10T00:00");
    const n = v.requests.length;
    await v.click("应用时间范围");
    expect(v.requests).toHaveLength(n);
    expect(v.host.textContent).toContain("31 天");
  } finally {
    await v.dispose();
  }
  const empty = await view((url) =>
    url.pathname.endsWith("/status")
      ? new Response(JSON.stringify({ ...status, configured: false }))
      : undefined,
  );
  try {
    expect(empty.host.textContent).toContain("尚未配置产测数据源");
    expect(empty.requests).toHaveLength(1);
  } finally {
    await empty.dispose();
  }
});
it("does not silently move selected main outside its investigation when browsing another symptom", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("关闭测试详情");
    await v.field("精确 SN", "DIFFERENT");
    await v.click("查询产测数据");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 400));
    });
    expect(v.host.textContent).toContain("当前浏览条件与主要事件不一致");
    expect(v.saved().context.sn).not.toBe("DIFFERENT");
  } finally {
    await v.dispose();
  }
});
it("keeps independent pending resolve alive when restoring a handoff changes selected project", async () => {
  let finish!: (r: Response) => void;
  let signal: AbortSignal | null | undefined;
  const v = await view(
    (url, init) =>
      url.pathname.endsWith("/resolve")
        ? new Promise((r) => {
            finish = r;
            signal = init?.signal;
          })
        : undefined,
    { handoffId },
  );
  try {
    expect(signal?.aborted).toBe(false);
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({
            captured_at: now,
            primary: {
              state: "changed",
              complete: true,
              candidates: [{ snapshot_id: snap, offset: 0, row: pass }],
            },
            comparison: null,
            logs: [],
          }),
        ),
      ),
    );
    await flush();
    expect(v.host.textContent).toContain("源内容可能变化");
  } finally {
    await v.dispose();
  }
});
it("does not reattach old dependent selections when explicitly replacing the main", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查看 SN-A 履历");
    await v.click("查看测试 2");
    await v.click("选作对照");
    await v.click("设为调查对象");
    expect(v.host.textContent).toContain("替换主要事件将移除");
    await v.click("确认替换主要事件");
    const body = JSON.parse(
      String(
        v.requests.filter((r) => r.init?.method === "PUT").at(-1)!.init!.body,
      ),
    );
    expect(body.primary.offset).toBe(1);
    expect(body.comparison).toBeUndefined();
    expect(body.logs).toBeUndefined();
  } finally {
    await v.dispose();
  }
});
it("shows unknown activity gaps on partial captures and observed empty buckets only on complete captures", async () => {
  const v = await view((url) =>
    url.searchParams.get("view") === "activity"
      ? new Response(
          JSON.stringify({
            captured_at: now,
            complete: false,
            bucket_minutes: 60,
            items: [{ ...aggregate, device: "PC07", timestamp: range.start }],
          }),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("现场上位机");
    expect(v.host.textContent).toContain("该时间格未知");
    expect(v.host.textContent).not.toContain("该格未观测到测试事件");
  } finally {
    await v.dispose();
  }
});
it("keeps local failed notes visibly unsaved on resume until explicit review", async () => {
  sessionStorage.setItem(
    `production-investigation:admin-A:${project.id}`,
    JSON.stringify({ id: draftId, pending: { note: "仅本机秘密修改" } }),
  );
  const v = await view();
  try {
    await v.click("项目 A");
    expect(v.host.textContent).toContain("本机未保存修改");
    expect(
      (v.host.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("仅本机秘密修改");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 400));
    });
    expect(v.requests.some((r) => r.init?.method === "PUT")).toBe(false);
    await v.click("提交本机修改");
    expect(v.saved().note).toBe("仅本机秘密修改");
  } finally {
    await v.dispose();
  }
});
it("limits saved logs to five and preserves escaped metadata / protected downloads", async () => {
  const v = await view((url) =>
    url.pathname.endsWith("/evidence")
      ? new Response(
          JSON.stringify(
            page(
              Array.from({ length: 6 }, (_, i) => ({
                id: String(i + 1),
                csn: "<script>alert(1)</script>",
                url: "https://private.invalid/file",
              })),
              { source_kind: "evidence" },
            ),
          ),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查找候选日志");
    expect(v.host.querySelector("script")).toBeNull();
    expect(v.host.querySelector('a[href^="https:"]')).toBeNull();
    for (let i = 1; i <= 5; i++) await v.click(`加入调查 ${i}`);
    expect(
      [...v.host.querySelectorAll("button")].find(
        (b) => b.textContent === "加入调查 6",
      )?.disabled,
    ).toBe(true);
    expect(v.saved().logs).toHaveLength(5);
  } finally {
    await v.dispose();
  }
});
it("keeps query capability failure distinct from empty source records", async () => {
  const v = await view((url) =>
    url.pathname.endsWith("/status") && url.pathname.includes("/projects/")
      ? new Response(
          JSON.stringify({
            ...status,
            capabilities: {
              ...status.capabilities,
              production: { available: false, reason: "SOURCE_UNAVAILABLE" },
            },
          }),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查记录");
    expect(v.host.textContent).toContain("生产测试查询能力尚未配置");
    expect(
      v.requests.some((r) => r.url.pathname.endsWith("/observations")),
    ).toBe(false);
  } finally {
    await v.dispose();
  }
});
it("shows resolved stopover candidates with their real source kind and candidate bounds", async () => {
  const v = await view(
    (url) =>
      url.pathname.includes("/handoffs/") && !url.pathname.endsWith("/resolve")
        ? new Response(
            JSON.stringify({
              ...initialDraft(),
              id: handoffId,
              primary: { ...selection(0), source_kind: "stopover" },
            }),
          )
        : url.pathname.endsWith("/resolve")
          ? new Response(
              JSON.stringify({
                captured_at: now,
                primary: {
                  state: "changed",
                  descriptor: fail,
                  complete: true,
                  candidates: [{ snapshot_id: snap, offset: 0, row: pass }],
                },
                comparison: null,
                logs: [],
              }),
            )
          : undefined,
    { handoffId },
  );
  try {
    expect(v.host.textContent).toContain("精确事件时间及 SN 的有界候选");
    await v.click("核对主要候选 1");
    expect(
      v.host.querySelector('[aria-label="测试详情"]')?.textContent,
    ).toContain("过站详情");
    expect(v.host.textContent).toContain("原定位与当前候选分别显示");
  } finally {
    await v.dispose();
  }
});
it("uses actual row identity labels when history crosses tools and supports parameter search", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("选择无线测试 · 无线工具");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("查看 SN-A 履历");
    await v.click("查看测试 3");
    expect(
      v.host.querySelector('[aria-label="测试详情"]')?.textContent,
    ).toContain("工具 18（名称未取得）");
    await v.field("搜索参数", "measurement");
    expect(
      v.host.querySelector('[aria-label="测试参数表"]')?.textContent,
    ).toContain("measurement10");
  } finally {
    await v.dispose();
  }
});
it("readable advanced selectors issue actual source IDs without exposing parent-ID entry", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.field("测试环节筛选", "7|8");
    await v.click("查询产测数据");
    const q = v.requests
      .filter((r) => r.url.pathname.endsWith("/observations"))
      .at(-1)!.url;
    expect(q.searchParams.get("stage_id")).toBe("7");
    expect(q.searchParams.get("software_id")).toBe("8");
  } finally {
    await v.dispose();
  }
});
it("copies a complete immutable handoff summary with scope, events and candidate log gaps", async () => {
  const writeText = vi.fn(async (_text: string) => {});
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  const v = await view(
    (url) =>
      url.pathname.includes("/handoffs/") && !url.pathname.endsWith("/resolve")
        ? new Response(
            JSON.stringify({
              ...initialDraft(),
              id: handoffId,
              context: {
                ...range,
                view: "anomalies",
                error_code: "E1",
                missing_fields: ["device"],
                symptom: "项目 A · 无线测试",
              },
              primary: selection(0),
              comparison: selection(1),
              logs: [
                {
                  source_log_id: "99999999999999999999",
                  descriptor: { csn: "OTHER-CSN" },
                  state: "unverified",
                },
              ],
              note: "仍需现场核对",
            }),
          )
        : undefined,
    { handoffId },
  );
  try {
    await v.click("复制交接摘要与恢复链接");
    const copied = writeText.mock.calls[0]?.[0] as string;
    expect(copied).toContain("无线测试");
    expect(copied).toContain("E1");
    expect(copied).toContain("上位机：源未提供");
    expect(copied).toContain("主要事件");
    expect(copied).toContain("对照事件");
    expect(copied).toContain("99999999999999999999");
    expect(copied).toContain("关联待核对");
    expect(copied).toContain("production_handoff=" + handoffId);
    expect(copied).not.toContain("measurement");
  } finally {
    await v.dispose();
  }
});
it("expands history independently while highlighting the original symptom and showing unknown source results", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(now));
  const v = await view((url) =>
    url.pathname.endsWith("/observations") && url.searchParams.get("sn")
      ? new Response(
          JSON.stringify(page([fail, pass, { ...pass, status: "9" }])),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("查看 SN-A 履历");
    expect(v.host.textContent).toContain("原症状命中");
    expect(v.host.textContent).toContain("结果未知（9）");
    expect(v.host.textContent).toContain("通过 PASS");
  } finally {
    await v.dispose();
    vi.useRealTimers();
  }
});
it("retains last successful overview data with its timestamp during retry failure", async () => {
  let failRead = false;
  const v = await view((url) =>
    failRead && url.pathname.endsWith("/overview")
      ? new Response("{}", { status: 503 })
      : undefined,
  );
  try {
    const failedSN = () => [...v.host.querySelectorAll(".pt-project-table tbody tr")]
      .find((row) => row.querySelector("th button")?.textContent === project.name)
      ?.querySelectorAll("td")[2].textContent;
    const updated = () => v.host.querySelector(".pt-updated time");
    expect(failedSN()).toBe("12");
    expect(updated()?.getAttribute("datetime")).toBe(now);
    expect(updated()?.textContent).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    failRead = true;
    await v.click("重新读取");
    expect(failedSN()).toBe("12");
    expect(updated()?.getAttribute("datetime")).toBe(now);
    expect(v.host.textContent).toContain("显示上次数据，尚未更新。");
    expect(v.host.textContent).toContain("数据源暂不可用");
  } finally {
    await v.dispose();
  }
});
it("offers an explicit latest actual window for an empty project without silently changing the original range", async () => {
  const v = await view((url) =>
    url.pathname.endsWith("/availability")
      ? new Response(
          JSON.stringify({
            captured_at: now,
            latest_at: "2026-10-20T08:00:00Z",
          }),
        )
      : url.searchParams.get("view") === "summary"
        ? new Response(
            JSON.stringify({
              captured_at: now,
              complete: true,
              items: [
                {
                  ...aggregate,
                  records: "0",
                  distinct_sn: "0",
                  failed_sn: "0",
                  first_time: null,
                  last_time: null,
                },
              ],
            }),
          )
        : undefined,
  );
  try {
    await v.click("项目 A");
    expect(v.host.textContent).toContain("当前范围无测试");
    const original = v.requests
      .filter((r) => r.url.searchParams.get("view") === "summary")
      .at(-1)!
      .url.searchParams.get("start");
    await v.click("查看最近实际数据时段");
    const selected = v.requests
      .filter((r) => r.url.searchParams.get("view") === "stages")
      .at(-1)!.url;
    expect(selected.searchParams.get("start")).not.toBe(original);
    expect(selected.searchParams.get("start")).toContain("2026-10-20");
  } finally {
    await v.dispose();
  }
});
it("saves direct SN history independently from original issue SN filters", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查 SN");
    await v.field("精确 SN", "SN-A");
    await v.click("查询产测数据");
    await v.click("开始调查");
    expect(v.saved().context.history_sn).toBe("SN-A");
    expect(v.saved().context.sn).toBeUndefined();
    expect(v.saved().context.history_range).toBeDefined();
  } finally {
    await v.dispose();
  }
});
it("shows changed fresh readings, selected anomaly trend and version-record drill", async () => {
  const v = await view((url) => url.searchParams.get("view") === "summary"
    ? new Response(JSON.stringify({
        captured_at: now,
        complete: true,
        items: [{ ...aggregate, records: "120", distinct_sn: "90" }],
      })) : undefined);
  try {
    await v.click("项目 A");
    expect(v.host.textContent).toContain("数据已变化：测试次数 100 → 120；测试 SN 80 → 90。");
    expect(v.host.textContent).not.toContain("父视图读取");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    expect(v.host.querySelector('[aria-label="所选异常趋势"]')).toBeNull();
    await v.click("查看趋势");
    expect(v.host.querySelector('[aria-label="所选异常趋势"]')).not.toBeNull();
    await v.click("工具与配置");
    await v.click("查看无线工具版本");
    await v.click("查看此版本测试");
    const q = v.requests
      .filter((r) => r.url.pathname.endsWith("/observations"))
      .at(-1)!.url;
    expect(q.searchParams.get("software_id")).toBe(project.id);
    expect(q.searchParams.get("software_version")).toBe("v2");
  } finally {
    await v.dispose();
  }
});

it("I1 advances live overview then freezes drill interval", async () => {
  let tick = () => {};
  const timer = vi.spyOn(window, "setInterval").mockImplementation(((
    f: () => void,
  ) => {
    tick = f;
    return 1;
  }) as typeof setInterval);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(now));
  const v = await view();
  try {
    const first = v.requests
      .filter((r) => r.url.pathname.endsWith("/overview"))
      .at(-1)!
      .url.searchParams.get("end");
    vi.setSystemTime(new Date(+new Date(now) + 60000));
    await act(async () => tick());
    await flush();
    const second = v.requests
      .filter((r) => r.url.pathname.endsWith("/overview"))
      .at(-1)!
      .url.searchParams.get("end");
    expect(second).not.toBe(first);
    await v.click("项目 A");
    vi.setSystemTime(new Date(+new Date(now) + 120000));
    await v.click("重新读取");
    expect(
      v.requests
        .filter((r) => r.url.searchParams.get("view") === "stages")
        .at(-1)!
        .url.searchParams.get("end"),
    ).toBe(second);
  } finally {
    await v.dispose();
    timer.mockRestore();
    vi.useRealTimers();
  }
});
it("I2 overview scope is global and never carries project A filters into B", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("限定上位机 PC07");
    await v.click("项目总览");
    expect(
      (v.host.querySelector('[aria-label="源项目"]') as HTMLSelectElement)
        .value,
    ).toBe("");
    expect(v.host.querySelector(".pt-chips")?.textContent).toBe("");
    await v.click("项目 B");
    const q = v.requests
      .filter((r) => r.url.searchParams.get("view") === "stages")
      .at(-1)!.url;
    expect(q.pathname).toContain(other.id);
    for (const k of [
      "device",
      "status",
      "error_code",
      "stage_id",
      "software_id",
      "missing_fields",
    ])
      expect(q.searchParams.has(k)).toBe(false);
  } finally {
    await v.dispose();
  }
});
for (const hasMain of [false, true])
  it(`I2 parent back preserves saved and handed context ${hasMain ? "with main" : "without main"}`, async () => {
    let handed: any;
    const v = await view((u, i) => {
      if (u.pathname.endsWith("/handoffs") && i?.method === "POST")
        handed = structuredClone(v.saved());
      return undefined;
    });
    try {
      await v.click("项目 A");
      await v.click("查看该范围失败");
      await v.click("选择异常 E1");
      if (hasMain) {
        await v.click("查看测试 1");
        await v.click("设为调查对象");
        await v.click("关闭测试详情");
      } else await v.click("开始调查");
      const original = structuredClone(v.saved().context);
      await v.click("返回");
      await v.click("返回");
      await act(async () => {
        await new Promise((r) => setTimeout(r, 400));
      });
      await v.click("生成交接摘要");
      expect(v.saved().context).toEqual(original);
      expect(handed.context).toEqual(original);
    } finally {
      await v.dispose();
    }
  });
it("I2 recent drill keeps device and symptom predicates and original issue interval", async () => {
  const v = await view((u) =>
    u.searchParams.get("view") === "activity"
      ? new Response(
          JSON.stringify({
            captured_at: now,
            complete: true,
            bucket_minutes: 5,
            items: [
              {
                ...aggregate,
                device: "PC07",
                timestamp: u.searchParams.get("start"),
              },
            ],
          }),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("查看上位机 PC07");
    await v.click("开始调查");
    const original = structuredClone(v.saved().context);
    await v.click("查看近况");
    await act(async () =>
      (
        v.host.querySelector(
          '[aria-label="近况活动"] button',
        ) as HTMLButtonElement
      ).click(),
    );
    await flush();
    const q = v.requests
      .filter((r) => r.url.pathname.endsWith("/observations"))
      .at(-1)!.url;
    expect(q.searchParams.get("device")).toBe("PC07");
    expect(q.searchParams.get("error_code")).toBe("E1");
    expect(q.searchParams.get("stage_id")).toBe("7");
    await v.click("返回");
    await v.click("生成交接摘要");
    expect(v.saved().context.start).toBe(original.start);
    expect(v.saved().context.end).toBe(original.end);
  } finally {
    await v.dispose();
  }
});
it("I3 failed first POST resumes idless local notes without project click or directory", async () => {
  const v = await view((u, i) =>
    u.pathname.endsWith("/investigations") && i?.method === "POST"
      ? new Response("{}", { status: 503 })
      : undefined,
  );
  await v.click("项目 A");
  await v.click("恢复调查");
  await v.field("观察事实和待确认事项", "首次创建失败仍须保留");
  await v.click("生成交接摘要");
  expect(v.host.textContent).toContain("保存失败");
  await v.dispose();
  const restored = await view((u) =>
    u.pathname.endsWith("/production-tools/projects")
      ? new Response("{}", { status: 503 })
      : undefined,
  );
  try {
    expect(restored.host.textContent).toContain("本机未保存修改");
    expect(
      (restored.host.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("首次创建失败仍须保留");
    expect(restored.requests.some((r) => r.init?.method === "POST")).toBe(
      false,
    );
    await restored.click("提交本机修改");
    expect(restored.saved().note).toBe("首次创建失败仍须保留");
  } finally {
    await restored.dispose();
  }
});
it("I3 active locator resumes authorized saved page without directory or selection", async () => {
  const v = await view();
  await v.click("项目 A");
  await v.click("查记录");
  await v.click("查看测试 1");
  await v.click("设为调查对象");
  const saved = structuredClone(v.saved());
  await v.dispose();
  const restored = await view((u) =>
    u.pathname.endsWith("/production-tools/projects")
      ? new Response("{}", { status: 503 })
      : u.pathname.endsWith("/" + draftId)
        ? new Response(JSON.stringify(saved))
        : undefined,
  );
  try {
    expect(restored.host.textContent).toContain(draftId);
    expect(restored.host.textContent).toContain("保存的定位：SN-A");
    expect(
      restored.requests.some((r) => r.url.pathname.endsWith("/" + draftId)),
    ).toBe(true);
    expect(
      (
        restored.host.querySelector(
          '[aria-label="源项目"]',
        ) as HTMLSelectElement
      ).value,
    ).toBe(project.id);
  } finally {
    await restored.dispose();
  }
});
it("I4 replacement clears verified candidate ownership immediately", async () => {
  const v = await view((u) =>
    u.pathname.endsWith("/resolve") && v.saved().primary?.offset === 1
      ? new Promise(() => {})
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("关闭测试详情");
    await v.click("按原条件复查证据");
    await v.click("查看 SN-A 履历");
    await v.click("查看测试 2");
    await v.click("设为调查对象");
    await v.click("确认替换主要事件");
    expect(v.saved().primary.offset).toBe(1);
    expect(
      [...v.host.querySelectorAll("button")].some(
        (b) => b.textContent === "核对主要候选 1",
      ),
    ).toBe(false);
    expect(
      v.host.querySelector('[aria-label="当前调查"]')?.textContent,
    ).not.toContain("内容已核对");
  } finally {
    await v.dispose();
  }
});
it("I4 reverse resolve completion cannot install stale raw rows or candidate identity", async () => {
  const pending: ((r: Response) => void)[] = [];
  const v = await view(
    (u) =>
      u.pathname.endsWith("/resolve")
        ? new Promise((r) => pending.push(r))
        : undefined,
    { handoffId },
  );
  try {
    await v.click("按原条件复查证据");
    expect(pending.length).toBeGreaterThanOrEqual(2);
    const resolved = (marker: string) =>
      new Response(
        JSON.stringify({
          captured_at: now,
          primary: {
            state: "verified",
            complete: true,
            candidates: [
              {
                snapshot_id: snap,
                offset: 0,
                row: { ...fail, measurement: marker },
              },
            ],
          },
          comparison: {
            state: "verified",
            complete: true,
            candidates: [{ snapshot_id: snap, offset: 1, row: pass }],
          },
          logs: [],
        }),
      );
    await act(async () => pending.at(-1)!(resolved("CURRENT-RAW")));
    await flush();
    await act(async () => pending[0](resolved("STALE-RAW")));
    await flush();
    await v.click("比较已选记录");
    expect(v.host.textContent).toContain("CURRENT-RAW");
    expect(v.host.textContent).not.toContain("STALE-RAW");
    await v.click("核对主要候选 1");
    expect(
      v.host.querySelector('[aria-label="测试详情"]')?.textContent,
    ).toContain("CURRENT-RAW");
  } finally {
    await v.dispose();
  }
});
it("I5 failed-save Back Stay reconciles native history before repeated Back Forward", async () => {
  const v = await view((u, i) =>
    u.pathname.includes(other.id + "/investigations") && i?.method === "POST"
      ? new Response("{}", { status: 503 })
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.field("源项目", other.id);
    await v.click("恢复调查");
    await v.field("观察事实和待确认事项", "B本机未保存");
    const originalIndex = history.state.productionWorkbench.index;
    await act(async () => history.back());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    await flush();
    expect(v.host.textContent).toContain("留在原页");
    await v.click("留在原页");
    expect(history.state.productionWorkbench.index).toBe(originalIndex);
    expect(
      (v.host.querySelector('[aria-label="源项目"]') as HTMLSelectElement)
        .value,
    ).toBe(other.id);
    await act(async () => history.back());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    await flush();
    await v.click("保留本机修改后离开");
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    await flush();
    expect(
      (v.host.querySelector('[aria-label="源项目"]') as HTMLSelectElement)
        .value,
    ).toBe(project.id);
    await act(async () => history.forward());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    await flush();
    expect(
      (v.host.querySelector('[aria-label="源项目"]') as HTMLSelectElement)
        .value,
    ).toBe(other.id);
    expect(
      (v.host.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("B本机未保存");
  } finally {
    await v.dispose();
  }
});
for (const fault of ["missing", "version", "selection"] as const)
  it(`I4 rejects server resolve binding ${fault}`, async () => {
    const binding = {
      kind: "handoff",
      id: handoffId,
      version: 1,
      primary_selection_id: selection(0).selection_id,
      comparison_selection_id: selection(1).selection_id,
    };
    const v = await view(
      (u) =>
        u.pathname.endsWith("/resolve")
          ? new Response(
              JSON.stringify({
                binding:
                  fault === "missing"
                    ? null
                    : {
                        ...binding,
                        ...(fault === "version"
                          ? { version: 2 }
                          : {
                              primary_selection_id: selection(2).selection_id,
                            }),
                      },
                captured_at: now,
                primary: {
                  state: "verified",
                  complete: true,
                  candidates: [
                    {
                      snapshot_id: snap,
                      offset: 2,
                      row: { ...pass, measurement: "WRONG-SERVER-OWNER" },
                    },
                  ],
                },
                comparison: {
                  state: "verified",
                  complete: true,
                  candidates: [
                    { snapshot_id: snap, offset: 1, row: comparisonPass },
                  ],
                },
                logs: [],
              }),
            )
          : undefined,
      { handoffId },
    );
    try {
      await v.click("比较已选记录");
      expect(v.host.textContent).not.toContain("WRONG-SERVER-OWNER");
      expect(v.host.textContent).toContain("当前参数未核对");
      expect(
        [...v.host.querySelectorAll("button")].some(
          (b) => b.textContent === "核对主要候选 1",
        ),
      ).toBe(false);
    } finally {
      await v.dispose();
    }
  });
it("I4 different same-project handoffs resolve in reverse order without crossing raw ownership", async () => {
  const secondId = "55555555-5555-4555-8555-555555555555",
    pending = new Map<string, (r: Response) => void>();
  const v = await view(
    (u) =>
      u.pathname.endsWith("/resolve")
        ? new Promise((r) =>
            pending.set(
              u.pathname.includes(secondId) ? secondId : handoffId,
              r,
            ),
          )
        : u.pathname.endsWith("/" + secondId)
          ? new Response(
              JSON.stringify({
                ...initialDraft(),
                id: secondId,
                primary: {
                  ...selection(2),
                  descriptor: { ...pass, sn: "SECOND-SN" },
                },
                comparison: selection(1),
                note: "第二份固定版本",
              }),
            )
          : undefined,
    { handoffId },
  );
  try {
    await v.field("交接号或内部恢复链接", secondId);
    await v.click("读取交接");
    const resolved = (id: string, offset: number, marker: string) =>
      new Response(
        JSON.stringify({
          binding: {
            kind: "handoff",
            id,
            version: 1,
            primary_selection_id: selection(offset).selection_id,
            comparison_selection_id: selection(1).selection_id,
          },
          captured_at: now,
          primary: {
            state: "verified",
            complete: true,
            candidates: [
              {
                snapshot_id: snap,
                offset,
                row: { ...sourceRow(offset), measurement: marker },
              },
            ],
          },
          comparison: {
            state: "verified",
            complete: true,
            candidates: [{ snapshot_id: snap, offset: 1, row: comparisonPass }],
          },
          logs: [],
        }),
      );
    await act(async () =>
      pending.get(secondId)!(resolved(secondId, 2, "SECOND-CURRENT")),
    );
    await act(async () =>
      pending.get(handoffId)!(resolved(handoffId, 0, "FIRST-STALE")),
    );
    await flush();
    await v.click("比较已选记录");
    expect(v.host.textContent).toContain("SECOND-SN");
    expect(v.host.textContent).toContain("SECOND-CURRENT");
    expect(v.host.textContent).not.toContain("FIRST-STALE");
  } finally {
    await v.dispose();
  }
});
it("I2 nullable recent bucket keeps exact missing predicates", async () => {
  const v = await view((u) =>
    u.searchParams.get("view") === "errors"
      ? new Response(
          JSON.stringify({
            captured_at: now,
            complete: true,
            items: [
              {
                ...aggregate,
                stage_id: "7",
                software_id: "8",
                error_code: null,
              },
            ],
          }),
        )
      : u.searchParams.get("view") === "devices"
        ? new Response(
            JSON.stringify({
              captured_at: now,
              complete: true,
              items: [{ ...aggregate, device: null }],
            }),
          )
        : u.searchParams.get("view") === "activity"
          ? new Response(
              JSON.stringify({
                captured_at: now,
                complete: true,
                bucket_minutes: 5,
                items: [
                  {
                    ...aggregate,
                    device: null,
                    timestamp: u.searchParams.get("start"),
                  },
                ],
              }),
            )
          : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查看该范围失败");
    await v.click("选择异常 源未提供错误码");
    await v.click("查看上位机 源未提供");
    await v.click("查看近况");
    await act(async () =>
      (
        v.host.querySelector(
          '[aria-label="近况活动"] button',
        ) as HTMLButtonElement
      ).click(),
    );
    await flush();
    const q = v.requests
      .filter((r) => r.url.pathname.endsWith("/observations"))
      .at(-1)!.url;
    expect(q.searchParams.get("missing_fields")).toBe("device,error_code");
    expect(q.searchParams.get("software_id")).toBe("8");
  } finally {
    await v.dispose();
  }
});
it("I3 active resume denial never displays local pending notes", async () => {
  sessionStorage.setItem(
    `production-investigation:admin-A:active`,
    JSON.stringify({ projectId: project.id, id: draftId }),
  );
  sessionStorage.setItem(
    `production-investigation:admin-A:${project.id}`,
    JSON.stringify({ id: draftId, pending: { note: "PRIVATE-UNAUTHORIZED" } }),
  );
  const v = await view((u) =>
    u.pathname.includes("/investigations")
      ? new Response("{}", { status: 403 })
      : undefined,
  );
  try {
    expect(v.host.textContent).not.toContain("PRIVATE-UNAUTHORIZED");
    expect(
      (v.host.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("");
  } finally {
    await v.dispose();
  }
});
it("Minor rejects different-tool comparison under an explicit tool investigation scope", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("选择无线测试 · 无线工具");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查看 SN-A 履历");
    await v.click("查看测试 3");
    await v.click("选作对照");
    expect(v.host.textContent).toContain("保存失败");
    expect(v.saved().comparison).toBeNull();
  } finally {
    await v.dispose();
  }
});
it("I2 explicit chip removal updates saved scope without retaining deleted predicates", async () => {
  const v = await view();
  try {
    await v.click("项目 A");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("开始调查");
    await v.click("错误码：E1 ×");
    await v.click("生成交接摘要");
    expect(v.saved().context.error_code).toBeUndefined();
    expect(v.saved().context.stage_id).toBe("7");
    expect(v.saved().context.status).toBe("2");
  } finally {
    await v.dispose();
  }
});

for (const action of ["edit", "selection", "save"] as const) {
  it(`I4 retires delayed handoff metadata after newer ${action}`, async () => {
    let finish!: (response: Response) => void;
    const v = await view((u) =>
      u.pathname.endsWith("/handoffs/" + handoffId)
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : undefined,
    );
    try {
      await v.click("项目 A");
      await v.click("查记录");
      await v.click("开始调查");
      await v.field("交接号或内部恢复链接", handoffId);
      await v.click("读取交接");
      const note = () =>
        v.host.querySelector("textarea") as HTMLTextAreaElement;
      expect(note().disabled).toBe(false);
      if (action === "edit") {
        await v.field("观察事实和待确认事项", "AFTER-RESTORE-REQUEST-UNSAVED");
      } else if (action === "selection") {
        await v.click("查看测试 1");
        await v.click("设为调查对象");
        await v.click("关闭测试详情");
      } else {
        await v.click("生成交接摘要");
      }
      await act(async () =>
        finish(
          new Response(
            JSON.stringify({
              ...initialDraft(),
              id: handoffId,
              note: "FROZEN-OLD-NOTE",
            }),
          ),
        ),
      );
      await flush();
      expect(note().value).toBe(
        action === "edit" ? "AFTER-RESTORE-REQUEST-UNSAVED" : "",
      );
      if (action === "edit") {
        expect(note().disabled).toBe(false);
        await v.click("重试保存");
        expect(v.saved().note).toBe("AFTER-RESTORE-REQUEST-UNSAVED");
      } else if (action === "selection") {
        expect(v.saved().primary?.offset).toBe(0);
        expect(note().disabled).toBe(false);
        expect(v.host.textContent).toContain("核对主要候选 1");
      } else {
        await v.click("返回我的调查");
        expect(note().value).toBe("");
      }
    } finally {
      await v.dispose();
    }
  });
}

it("I4 newer local edit retires cached startup metadata too", async () => {
  const first = await view();
  await first.click("项目 A");
  await first.click("开始调查");
  await first.dispose();
  let finish!: (response: Response) => void;
  const v = await view((u, init) =>
    u.pathname.endsWith("/investigations/" + draftId) && init?.method === "GET"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined,
  );
  try {
    await v.click("恢复调查");
    await v.field("观察事实和待确认事项", "EDIT-DURING-STARTUP-RESTORE");
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({
            ...initialDraft(),
            note: "OLD-CACHED-SERVER-NOTE",
          }),
        ),
      ),
    );
    await flush();
    expect(
      (v.host.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("EDIT-DURING-STARTUP-RESTORE");
    expect(v.host.textContent).toContain("未保存修改");
  } finally {
    await v.dispose();
  }
});

for (const transition of ["subject", "fresh", "same-subject-search"] as const) {
  it(`F1 query-owned history cursor retires on ${transition}`, async () => {
    const v = await view((u) =>
      u.pathname.endsWith("/observations")
        ? new Response(
            JSON.stringify(
              page(
                u.searchParams.get("kind") === "stopover"
                  ? []
                  : [{ ...fail, sn: u.searchParams.get("sn") || "SN-A" }],
                {
                  has_more: u.searchParams.get("kind") !== "stopover",
                  captured_count: 100,
                },
              ),
            ),
          )
        : u.pathname.includes("/snapshots/") && transition === "fresh"
          ? new Response("{}", { status: 410 })
          : undefined,
    );
    try {
      await v.click("项目 A");
      await v.click("查记录");
      await v.click("查看 SN-A 履历");
      await v.click("下一页快照");
      const n = v.requests.length;
      if (transition !== "fresh") {
        await v.field("精确 SN", transition === "subject" ? "SN-B" : "SN-A");
        await v.click("查询产测数据");
      } else await v.click("重新读取");
      const reads = v.requests
        .slice(n)
        .filter((r) => r.url.pathname.endsWith("/observations"));
      expect(
        reads.some(
          (r) =>
            r.url.searchParams.get("kind") === "production" &&
            r.url.searchParams.get("sn") ===
              (transition === "subject" ? "SN-B" : "SN-A"),
        ),
      ).toBe(true);
      expect(
        v.requests.slice(n).some((r) => r.url.pathname.includes("/snapshots/")),
      ).toBe(false);
      if (transition === "subject")
        expect(v.host.textContent).not.toContain("查看 SN-A 履历");
    } finally {
      await v.dispose();
    }
  });
}

for (const [key, label, value] of [
  ["error_code", "错误码", "E2"],
  ["device", "精确设备", "PC02"],
  ["software_version", "软件版本", "v3"],
  ["config_version", "配置版本", "c3"],
] as const) {
  it(`F2 normal exact ${key} edit replaces restored missing predicate in request and persisted context`, async () => {
    const v = await view(
      (u) =>
        u.pathname.endsWith("/handoffs/" + handoffId) ||
        u.pathname.endsWith("/fork")
          ? new Response(
              JSON.stringify({
                ...initialDraft(),
                id: u.pathname.endsWith("/fork") ? draftId : handoffId,
                context: { ...range, view: "records", missing_fields: [key] },
              }),
            )
          : undefined,
      { handoffId },
    );
    try {
      await v.click("另存为我的调查");
      // Fork adopts the frozen query; fixture returns its stored draft by default.
      await v.field(label, value);
      await v.click("查询产测数据");
      await v.click("重试保存");
      const q = v.requests
        .filter((r) => r.url.pathname.endsWith("/observations"))
        .at(-1)!.url;
      expect(q.searchParams.get(key)).toBe(value);
      expect(
        (q.searchParams.get("missing_fields") || "").split(","),
      ).not.toContain(key);
      expect(v.saved().context[key]).toBe(value);
      expect(v.saved().context.missing_fields || []).not.toContain(key);
    } finally {
      await v.dispose();
    }
  });
}

for (const operation of ["fork", "generate"] as const) {
  it(`F3 superseded ${operation} cannot adopt metadata or erase pending edits`, async () => {
    let finish!: (r: Response) => void;
    const forkId = "55555555-5555-4555-8555-555555555555";
    const v = await view((u, i) =>
      (
        operation === "fork"
          ? u.pathname.endsWith("/fork")
          : u.pathname.endsWith("/handoffs") && i?.method === "POST"
      )
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : undefined,
    );
    try {
      await v.click("项目 A");
      await v.click("查记录");
      await v.click("开始调查");
      if (operation === "fork") {
        await v.field("交接号或内部恢复链接", handoffId);
        await v.click("读取交接");
        await v.click("另存为我的调查");
        await v.click("返回我的调查");
      } else await v.click("生成交接摘要");
      await v.field("观察事实和待确认事项", "NEW-LOCAL-EDIT");
      await act(async () =>
        finish(
          new Response(
            JSON.stringify({
              ...initialDraft(),
              id: operation === "fork" ? forkId : handoffId,
              note: "OLD-HANDOFF",
            }),
          ),
        ),
      );
      await flush();
      const note = v.host.querySelector("textarea") as HTMLTextAreaElement;
      expect(note.value).toBe("NEW-LOCAL-EDIT");
      expect(note.disabled).toBe(false);
      expect(JSON.stringify(Object.values(sessionStorage))).not.toContain(
        forkId,
      );
      await v.click("重试保存");
      const put = v.requests.filter((r) => r.init?.method === "PUT").at(-1)!;
      expect(put.url.pathname).toContain(draftId);
      expect(JSON.parse(String(put.init!.body)).note).toBe("NEW-LOCAL-EDIT");
    } finally {
      await v.dispose();
    }
  });
}

it("F4 actual candidate capture and F5 synchronous selection guard preserve accepted add/remove operations", async () => {
  let finish!: (r: Response) => void;
  let defer = false;
  let pendingBody: any;
  const v = await view((u, i) => {
    if (u.pathname.endsWith("/evidence"))
      return new Response(
        JSON.stringify(
          page(
            [
              { id: "101", csn: "C1" },
              { id: "102", csn: "C2" },
              { id: "103", csn: "C3" },
            ],
            { source_kind: "evidence", offset: 50 },
          ),
        ),
      );
    if (defer && i?.method === "PUT") {
      pendingBody = JSON.parse(String(i.body));
      return new Promise((resolve) => {
        finish = resolve;
      });
    }
  });
  const button = (id: string) =>
    [...v.host.querySelectorAll("button")].find(
      (b) => b.textContent === "加入调查 " + id,
    )!;
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查找候选日志");
    defer = true;
    await v.click("加入调查 101");
    expect(button("102").disabled).toBe(true);
    expect(pendingBody.logs).toEqual([
      { snapshot_id: snap, offset: 50, source_log_id: "101" },
    ]);
    await v.click("加入调查 102");
    defer = false;
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({
            ...v.saved(),
            version: v.saved().version + 1,
            logs: [{ source_log_id: "101", descriptor: { csn: "C1" } }],
          }),
        ),
      ),
    );
    await flush();
    await v.click("加入调查 102");
    expect(v.saved().logs.map((l: any) => l.source_log_id)).toEqual([
      "101",
      "102",
    ]);
    defer = true;
    await v.click("移除日志 101");
    expect(button("103").disabled).toBe(true);
    const puts = v.requests.filter((r) => r.init?.method === "PUT").length;
    await v.click("加入调查 103");
    expect(v.requests.filter((r) => r.init?.method === "PUT")).toHaveLength(
      puts,
    );
    defer = false;
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({
            ...v.saved(),
            version: v.saved().version + 1,
            logs: [{ source_log_id: "102", descriptor: { csn: "C2" } }],
          }),
        ),
      ),
    );
    await flush();
    await v.click("加入调查 103");
    expect(v.saved().logs.map((l: any) => l.source_log_id)).toEqual([
      "102",
      "103",
    ]);
  } finally {
    await v.dispose();
  }
});

it("F1 paged anomaly changes scope without reusing capture and back restores exact paged location", async () => {
  const v = await view((u) => {
    if (
      u.pathname.endsWith("/analysis") &&
      u.searchParams.get("view") === "errors"
    )
      return new Response(
        JSON.stringify({
          ...block,
          source_project_id: project.id,
          items: ["E1", "E2"].map((error_code) => ({
            ...aggregate,
            key: error_code,
            stage_id: "7",
            software_id: "8",
            error_code,
          })),
        }),
      );
    if (u.pathname.endsWith("/observations"))
      return new Response(
        JSON.stringify(
          page([{ ...fail, errorcode: u.searchParams.get("error_code") }], {
            has_more: true,
            captured_count: 100,
          }),
        ),
      );
  });
  try {
    await v.click("项目 A");
    await v.click("查看该范围失败");
    await v.click("选择异常 E1");
    await v.click("下一页快照");
    const n = v.requests.length;
    await v.click("选择异常 E2");
    const reads = v.requests
      .slice(n)
      .filter((r) => r.url.pathname.endsWith("/observations"));
    expect(reads.at(-1)!.url.searchParams.get("error_code")).toBe("E2");
    expect(
      v.requests.slice(n).some((r) => r.url.pathname.includes("/snapshots/")),
    ).toBe(false);
    await v.click("返回");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    await flush();
    expect(
      v.requests
        .filter((r) => r.url.pathname.includes("/snapshots/"))
        .at(-1)!
        .url.searchParams.get("offset"),
    ).toBe("50");
    expect(v.host.textContent).toContain("错误码：E1");
  } finally {
    await v.dispose();
  }
});

for (const dimension of ["error", "device", "versions"] as const) {
  it(`F2 exact to missing ${dimension} through normal drill persists exclusive predicates`, async () => {
    const context = {
      ...range,
      view: "anomalies",
      error_code: "E1",
      device: "PC07",
      software_id: "8",
      software_version: "v2",
      config_log_id: "9",
      config_version: "c2",
    };
    const v = await view(
      (u) => {
        if (
          u.pathname.endsWith("/handoffs/" + handoffId) ||
          u.pathname.endsWith("/fork")
        )
          return new Response(
            JSON.stringify({
              ...initialDraft(),
              id: u.pathname.endsWith("/fork") ? draftId : handoffId,
              context,
            }),
          );
        if (
          u.pathname.endsWith("/analysis") &&
          ["errors", "devices", "versions"].includes(
            u.searchParams.get("view")!,
          )
        )
          return new Response(
            JSON.stringify({
              ...block,
              items: [
                {
                  ...aggregate,
                  stage_id: "7",
                  software_id: "8",
                  error_code: null,
                  device: null,
                  software_version: null,
                  config_log_id: "9",
                  config_version: null,
                },
              ],
            }),
          );
      },
      { handoffId },
    );
    try {
      await v.click("另存为我的调查");
      if (dimension === "error") await v.click("选择异常 源未提供错误码");
      else if (dimension === "device") await v.click("限定上位机 源未提供");
      else {
        const select = [...v.host.querySelectorAll("select")].find((s) =>
          s.querySelector('option[value="versions"]'),
        )!;
        await act(async () => {
          Object.getOwnPropertyDescriptor(
            HTMLSelectElement.prototype,
            "value",
          )!.set!.call(select, "versions");
          select.dispatchEvent(new Event("change", { bubbles: true }));
        });
        await flush();
        await v.click("限定版本 源未提供 / 源未提供");
      }
      await v.click("查记录");
      await v.click("重试保存");
      const q = v.requests
        .filter((r) => r.url.pathname.endsWith("/observations"))
        .at(-1)!.url;
      for (const key of dimension === "error"
        ? ["error_code"]
        : dimension === "device"
          ? ["device"]
          : ["software_version", "config_version"]) {
        expect(q.searchParams.has(key)).toBe(false);
        expect(q.searchParams.get("missing_fields")?.split(",")).toContain(key);
        expect(v.saved().context[key]).toBeUndefined();
        expect(v.saved().context.missing_fields).toContain(key);
      }
    } finally {
      await v.dispose();
    }
  });
}

it("F2 changing stage/tool through advanced control clears inherited dependent versions and missing flags", async () => {
  const context = {
    ...range,
    view: "records",
    stage_id: "70",
    software_id: "80",
    software_version: "old",
    config_log_id: "90",
    missing_fields: ["config_version"],
  };
  const v = await view(
    (u) =>
      u.pathname.endsWith("/handoffs/" + handoffId) ||
      u.pathname.endsWith("/fork")
        ? new Response(
            JSON.stringify({
              ...initialDraft(),
              id: u.pathname.endsWith("/fork") ? draftId : handoffId,
              context,
            }),
          )
        : undefined,
    { handoffId },
  );
  try {
    await v.click("另存为我的调查");
    await v.field("测试环节筛选", "7|8");
    await v.click("查询产测数据");
    await v.click("重试保存");
    const q = v.requests
      .filter((r) => r.url.pathname.endsWith("/observations"))
      .at(-1)!.url;
    expect(q.searchParams.get("stage_id")).toBe("7");
    expect(q.searchParams.get("software_id")).toBe("8");
    for (const key of ["software_version", "config_log_id", "config_version"]) {
      expect(q.searchParams.has(key)).toBe(false);
      expect(
        q.searchParams.get("missing_fields")?.split(",") || [],
      ).not.toContain(key);
      expect(v.saved().context[key]).toBeUndefined();
    }
  } finally {
    await v.dispose();
  }
});

it("F5 five unique accepted logs disable additions without extra PUTs", async () => {
  const v = await view((u) =>
    u.pathname.endsWith("/evidence")
      ? new Response(
          JSON.stringify(
            page(
              Array.from({ length: 6 }, (_, i) => ({
                id: String(101 + i),
                csn: "C" + i,
              })),
              { source_kind: "evidence" },
            ),
          ),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查找候选日志");
    for (let i = 101; i <= 105; i++) await v.click("加入调查 " + i);
    const count = v.requests.filter((r) => r.init?.method === "PUT").length;
    await v.click("加入调查 106");
    await v.click("加入调查 101");
    expect(v.requests.filter((r) => r.init?.method === "PUT")).toHaveLength(
      count,
    );
    expect(v.saved().logs.map((l: any) => l.source_log_id)).toEqual([
      "101",
      "102",
      "103",
      "104",
      "105",
    ]);
  } finally {
    await v.dispose();
  }
});

it("F3 own save acknowledgement advances revision while preserving newer pending edit", async () => {
  let finish!: (r: Response) => void;
  let deferred = true;
  const v = await view((u, i) =>
    i?.method === "PUT" && deferred
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("开始调查");
    await v.field("观察事实和待确认事项", "FIRST");
    await v.click("重试保存");
    await v.field("观察事实和待确认事项", "NEWER");
    deferred = false;
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({ ...v.saved(), version: 2, note: "FIRST" }),
        ),
      ),
    );
    await flush();
    expect(
      (v.host.querySelector("textarea") as HTMLTextAreaElement).value,
    ).toBe("NEWER");
    const cached = JSON.parse(
      sessionStorage.getItem("production-investigation:admin-A:" + project.id)!,
    );
    expect(cached.pending.note).toBe("NEWER");
    await v.click("重试保存");
    const body = JSON.parse(
      String(
        v.requests.filter((r) => r.init?.method === "PUT").at(-1)!.init!.body,
      ),
    );
    expect(body.expected_version).toBe(2);
    expect(body.note).toBe("NEWER");
    expect(v.saved().version).toBe(3);
  } finally {
    await v.dispose();
  }
});

it("F3 same-project navigation retires a generated handoff adoption", async () => {
  let finish!: (r: Response) => void;
  const v = await view((u, i) =>
    u.pathname.endsWith("/handoffs") && i?.method === "POST"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("开始调查");
    await v.click("生成交接摘要");
    await v.click("查记录");
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({
            ...initialDraft(),
            id: handoffId,
            note: "OLD-GENERATED",
          }),
        ),
      ),
    );
    await flush();
    expect(
      (v.host.querySelector("textarea") as HTMLTextAreaElement).disabled,
    ).toBe(false);
    expect(v.host.textContent).not.toContain("固定交接版本已生成");
    expect(
      JSON.parse(
        sessionStorage.getItem(
          "production-investigation:admin-A:" + project.id,
        )!,
      ).id,
    ).toBe(draftId);
  } finally {
    await v.dispose();
  }
});

it("F2 edited stage labels match the serialized scope after an earlier named drill", async () => {
  const v = await view((u) =>
    u.pathname.endsWith("/analysis") && u.searchParams.get("view") === "stages"
      ? new Response(
          JSON.stringify({
            ...block,
            source_project_id: project.id,
            items: [
              {
                ...aggregate,
                stage_id: "7",
                stage_name: "无线测试",
                software_id: "8",
                software_name: "无线工具",
              },
              {
                ...aggregate,
                stage_id: "70",
                stage_name: "新阶段",
                software_id: "80",
                software_name: "新工具",
              },
            ],
          }),
        )
      : undefined,
  );
  try {
    await v.click("项目 A");
    await v.click("选择无线测试 · 无线工具");
    await v.click("查记录");
    await v.field("测试环节筛选", "70|80");
    await v.click("查询产测数据");
    expect(v.host.textContent).toContain("阶段：新阶段");
    expect(v.host.textContent).toContain("工具：新工具");
    const q = v.requests
      .filter((r) => r.url.pathname.endsWith("/observations"))
      .at(-1)!.url;
    expect(q.searchParams.get("stage_id")).toBe("70");
    expect(q.searchParams.get("software_id")).toBe("80");
  } finally {
    await v.dispose();
  }
});

it("F5 failed add stays in the effective pending set for the next accepted add", async () => {
  let failSave = true;
  const v = await view((u, i) => {
    if (u.pathname.endsWith("/evidence"))
      return new Response(
        JSON.stringify(
          page(
            [
              { id: "101", csn: "A" },
              { id: "102", csn: "B" },
            ],
            { source_kind: "evidence" },
          ),
        ),
      );
    if (i?.method === "PUT" && failSave)
      return new Response("{}", { status: 503 });
  });
  try {
    await v.click("项目 A");
    await v.click("查记录");
    await v.click("查看测试 1");
    await v.click("设为调查对象");
    await v.click("查找候选日志");
    await v.click("加入调查 101");
    expect(v.host.textContent).toContain("保存失败");
    const cached = JSON.parse(
      sessionStorage.getItem("production-investigation:admin-A:" + project.id)!,
    );
    expect(cached.pending.logs[0].source_log_id).toBe("101");
    failSave = false;
    await v.click("加入调查 102");
    const body = JSON.parse(
      String(
        v.requests.filter((r) => r.init?.method === "PUT").at(-1)!.init!.body,
      ),
    );
    expect(body.logs.map((log: any) => log.source_log_id)).toEqual([
      "101",
      "102",
    ]);
    expect(v.saved().logs.map((log: any) => log.source_log_id)).toEqual([
      "101",
      "102",
    ]);
  } finally {
    await v.dispose();
  }
});

for (const startingPage of ["initial", "paged"] as const) {
  it(`R6 same-SN fresh search from ${startingPage} rereads both production and stopover`, async () => {
    let generation = "BEFORE";
    const v = await view((u) =>
      u.pathname.endsWith("/observations")
        ? new Response(
            JSON.stringify(
              page(
                [
                  {
                    ...fail,
                    devicename: generation + "-" + u.searchParams.get("kind"),
                  },
                ],
                { has_more: true, captured_count: 100 },
              ),
            ),
          )
        : undefined,
    );
    try {
      await v.click("项目 A");
      await v.click("查记录");
      await v.click("查看 SN-A 履历");
      await v.field("精确 SN", "SN-A");
      if (startingPage === "paged") await v.click("下一页快照");
      const before = v.requests.length;
      generation = "AFTER";
      await v.click("查询产测数据");
      const reads = v.requests
        .slice(before)
        .filter((r) => r.url.pathname.endsWith("/observations"));
      expect(reads.map((r) => r.url.searchParams.get("kind")).sort()).toEqual([
        "production",
        "stopover",
      ]);
      expect(reads.every((r) => r.url.searchParams.get("sn") === "SN-A")).toBe(
        true,
      );
      expect(
        v.requests
          .slice(before)
          .some((r) => r.url.pathname.includes("/snapshots/")),
      ).toBe(false);
      expect(v.host.textContent).toContain("AFTER-production");
      expect(v.host.textContent).toContain("AFTER-stopover");
      expect(v.host.textContent).not.toContain("BEFORE-");
    } finally {
      await v.dispose();
    }
  });
}

for (const [stage, tool, version] of [
  ["70", null, null],
  ["70", null, "EXPLICIT-V3"],
  [null, "80", null],
  [null, null, null],
] as const) {
  it(`R7 atomic advanced stage/tool edit ${stage}/${tool}/${version} preserves explicit predicates in source and saved context`, async () => {
    const context = {
      ...range,
      view: "records",
      stage_id: "7",
      software_id: "8",
      software_version: "OLD-V2",
      config_log_id: "9",
      config_version: "OLD-C2",
    };
    const v = await view(
      (u) => {
        if (
          u.pathname.endsWith("/handoffs/" + handoffId) ||
          u.pathname.endsWith("/fork")
        )
          return new Response(
            JSON.stringify({
              ...initialDraft(),
              id: u.pathname.endsWith("/fork") ? draftId : handoffId,
              context,
            }),
          );
        if (
          u.pathname.endsWith("/analysis") &&
          u.searchParams.get("view") === "stages"
        )
          return new Response(
            JSON.stringify({
              ...block,
              source_project_id: project.id,
              items: [
                {
                  ...aggregate,
                  stage_id: stage,
                  software_id: tool,
                  stage_name: stage ? "新阶段" : null,
                  software_name: tool ? "新工具" : null,
                },
              ],
            }),
          );
      },
      { handoffId },
    );
    try {
      await v.click("另存为我的调查");
      await v.field(
        "测试环节筛选",
        `${stage || "missing"}|${tool || "missing"}`,
      );
      if (version) await v.field("软件版本", version);
      await v.click("查询产测数据");
      await v.click("重试保存");
      const q = v.requests
        .filter((r) => r.url.pathname.endsWith("/observations"))
        .at(-1)!.url;
      for (const [key, value] of [
        ["stage_id", stage],
        ["software_id", tool],
      ] as const) {
        expect(q.searchParams.get(key)).toBe(value);
        expect(v.saved().context[key]).toBe(value || undefined);
        if (value) {
          expect(
            q.searchParams.get("missing_fields")?.split(",") || [],
          ).not.toContain(key);
          expect(v.saved().context.missing_fields || []).not.toContain(key);
        } else {
          expect(q.searchParams.get("missing_fields")?.split(",")).toContain(
            key,
          );
          expect(v.saved().context.missing_fields).toContain(key);
        }
      }
      expect(q.searchParams.get("software_version")).toBe(version);
      expect(v.saved().context.software_version).toBe(version || undefined);
      expect(q.searchParams.has("config_log_id")).toBe(false);
      expect(q.searchParams.has("config_version")).toBe(false);
      expect(v.saved().context.config_log_id).toBeUndefined();
      expect(v.saved().context.config_version).toBeUndefined();
    } finally {
      await v.dispose();
    }
  });
}

it("R7 version distribution preserves explicitly missing versions when both parent objects change", async () => {
  const context = {
    ...range,
    view: "anomalies",
    stage_id: "7",
    software_id: "8",
    software_version: "OLD-V2",
    config_log_id: "9",
    config_version: "OLD-C2",
    error_code: "E1",
  };
  const v = await view(
    (u) => {
      if (
        u.pathname.endsWith("/handoffs/" + handoffId) ||
        u.pathname.endsWith("/fork")
      )
        return new Response(
          JSON.stringify({
            ...initialDraft(),
            id: u.pathname.endsWith("/fork") ? draftId : handoffId,
            context,
          }),
        );
      if (
        u.pathname.endsWith("/analysis") &&
        u.searchParams.get("view") === "versions"
      )
        return new Response(
          JSON.stringify({
            ...block,
            source_project_id: project.id,
            items: [
              {
                ...aggregate,
                software_id: "80",
                software_version: null,
                config_log_id: "90",
                config_version: null,
              },
            ],
          }),
        );
    },
    { handoffId },
  );
  try {
    await v.click("另存为我的调查");
    const select = [...v.host.querySelectorAll("select")].find((s) =>
      s.querySelector('option[value="versions"]'),
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLSelectElement.prototype,
        "value",
      )!.set!.call(select, "versions");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await flush();
    await v.click("限定版本 源未提供 / 源未提供");
    await v.click("查记录");
    await v.click("重试保存");
    const q = v.requests
      .filter((r) => r.url.pathname.endsWith("/observations"))
      .at(-1)!.url;
    expect(q.searchParams.get("software_id")).toBe("80");
    expect(q.searchParams.get("config_log_id")).toBe("90");
    expect(v.saved().context.software_id).toBe("80");
    expect(v.saved().context.config_log_id).toBe("90");
    for (const key of ["software_version", "config_version"]) {
      expect(q.searchParams.has(key)).toBe(false);
      expect(q.searchParams.get("missing_fields")?.split(",")).toContain(key);
      expect(v.saved().context[key]).toBeUndefined();
      expect(v.saved().context.missing_fields).toContain(key);
    }
  } finally {
    await v.dispose();
  }
});

it("switches between version usage and explicit directory while preserving project selection mode", async () => {
  const v = await view();
  try {
    expect([...v.host.querySelectorAll('[aria-label="产测主导航"] button')].map(b => b.textContent)).toEqual(["项目总览", "失败分析", "现场上位机", "版本使用"]);
    await v.click("版本使用"); await v.click("查看版本");
    expect(v.host.querySelector('[aria-label="实际版本组合"]')).not.toBeNull();
    await v.click("工具与配置"); expect(v.host.querySelector('[aria-label="目录分类"]')).not.toBeNull();
    await v.field("源项目", other.id);
    expect(v.host.querySelector('[aria-label="目录分类"]')).not.toBeNull();
    await v.click("版本使用"); expect(v.host.querySelector('[aria-label="实际版本组合"]')).not.toBeNull();
    expect(v.host.querySelector('[aria-label="目录分类"]')).toBeNull();
    await v.field("源项目", ""); await v.click("项目 A");
    expect(v.host.querySelector('[aria-label="实际版本组合"]')).not.toBeNull();
  } finally { await v.dispose(); }
});
it("restores saved catalog scope into version usage after an explicit nested directory", async () => {
  const exact = { start: "2026-11-10T01:40:59.123Z", end: "2026-11-10T02:50:31.456Z", stage_id: "7", software_id: "9007199254740993", software_version: "v2", config_log_id: "9007199254740994", missing_fields: ["config_version"] };
  const v = await view(u => u.pathname.endsWith("/handoffs/" + handoffId) ? new Response(JSON.stringify({ ...initialDraft(), id: handoffId, context: { ...exact, view: "catalog" } })) : undefined);
  try {
    await v.click("项目 A"); await v.click("工具与配置"); await v.click("查看无线工具版本");
    await v.click("恢复调查"); await v.field("交接号或内部恢复链接", handoffId); await v.click("读取交接");
    expect(v.host.querySelector('[aria-label="实际版本组合"]')).not.toBeNull();
    expect(v.host.querySelector('[aria-label="目录分类"]')).toBeNull();
    const request = v.requests.filter(r => r.url.pathname.endsWith("/analysis") && r.url.searchParams.get("view") === "versions").at(-1)!.url;
    for (const [key, value] of Object.entries(exact)) expect(request.searchParams.get(key)).toBe(Array.isArray(value) ? value.join(",") : value);
  } finally { await v.dispose(); }
});

it("follows a version combination through a machine symptom to SN and event detail without losing scope", async () => {
  const v = await view();
  try {
    await v.click("版本使用"); await v.click("查看版本");
    const versionRead = v.requests.filter(r => r.url.pathname.endsWith("/analysis") && r.url.searchParams.get("view") === "versions").at(-1)!.url;
    const exact = { start: versionRead.searchParams.get("start")!, end: versionRead.searchParams.get("end")!, stage_id: "7", software_id: "8", software_version: "v2", config_log_id: "9", config_version: "c2" };
    await v.click("查看上位机"); await v.click("进入上位机");
    expect(v.host.querySelector('[aria-label="上位机症状"] table')).not.toBeNull();
    const machineRead = v.requests.filter(r => r.url.pathname.endsWith("/analysis") && r.url.searchParams.get("view") === "errors").at(-1)!.url;
    for (const [key, value] of Object.entries({ ...exact, device: "PC07" })) expect(machineRead.searchParams.get(key)).toBe(value);
    await v.click("分析此症状");
    const errors = v.requests.filter(r => r.url.pathname.endsWith("/analysis") && r.url.searchParams.get("view") === "errors").at(-1)!.url;
    for (const [key, value] of Object.entries({ ...exact, device: "PC07" })) expect(errors.searchParams.get(key)).toBe(value);
    expect(errors.searchParams.has("status")).toBe(false); expect(errors.searchParams.has("error_code")).toBe(false);
    const distribution = v.requests.filter(r => r.url.pathname.endsWith("/analysis") && r.url.searchParams.get("view") === "devices").at(-1)!.url;
    for (const [key, value] of Object.entries({ ...exact, device: "PC07", status: "2", error_code: "E1" })) expect(distribution.searchParams.get(key)).toBe(value);
    await v.click("查看失败记录");
    const records = v.requests.filter(r => r.url.pathname.endsWith("/observations")).at(-1)!.url;
    for (const [key, value] of Object.entries({ ...exact, device: "PC07", status: "2", error_code: "E1" })) expect(records.searchParams.get(key)).toBe(value);
    await v.click("查看 SN-A 履历");
    const history = v.requests.filter(r => r.url.pathname.endsWith("/observations") && r.url.searchParams.get("sn") === "SN-A").at(-1)!.url;
    expect(history.searchParams.get("start")).toBe(exact.start); expect(history.searchParams.get("end")).toBe(exact.end);
    for (const key of ["stage_id", "software_id", "software_version", "config_log_id", "config_version", "device", "error_code", "status"]) expect(history.searchParams.has(key)).toBe(false);
    await v.click("查看测试 1");
    expect(v.host.querySelector('[aria-label="测试详情"]')).not.toBeNull();
    expect(v.host.textContent).toContain("SN-A");
  } finally { await v.dispose(); }
});

it("opens failed version tests directly and keeps their SN and detail journey reachable", async () => {
  const v = await view();
  try {
    await v.click("版本使用"); await v.click("查看版本"); await v.click("查看失败");
    const records = v.requests.filter(r => r.url.pathname.endsWith("/observations")).at(-1)!.url;
    for (const [key, value] of Object.entries({ stage_id: "7", software_id: "8", software_version: "v2", config_log_id: "9", config_version: "c2", status: "2" })) expect(records.searchParams.get(key)).toBe(value);
    expect(records.searchParams.has("error_code")).toBe(false);
    await v.click("查看 SN-A 履历"); await v.click("查看测试 1");
    expect(v.host.querySelector('[aria-label="测试详情"]')).not.toBeNull();
  } finally { await v.dispose(); }
});
