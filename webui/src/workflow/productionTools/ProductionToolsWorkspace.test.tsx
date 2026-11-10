import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { createWorkflowApi } from "../api";
import { flush } from "../testHelpers";
import { ProductionToolsWorkspace } from "./ProductionToolsWorkspace";
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
  selection_id: "selection",
  snapshot_id: snap,
  offset,
  descriptor: offset ? pass : fail,
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
  const response = (data: unknown) => new Response(JSON.stringify(data));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input, init) => {
      const url = new URL(String(input), location.origin);
      requests.push({ url, init });
      const override = intercept(url, init);
      if (override) return override;
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
      if (path.endsWith("/resolve"))
        return response({
          captured_at: now,
          primary: saved.primary
            ? {
                state: "verified",
                descriptor: fail,
                complete: true,
                candidates: [{ snapshot_id: snap, offset: 0, row: fail }],
              }
            : null,
          comparison: saved.comparison
            ? {
                state: "verified",
                descriptor: pass,
                complete: true,
                candidates: [{ snapshot_id: snap, offset: 1, row: pass }],
              }
            : null,
          logs: [],
        });
      if (path.endsWith("/fork"))
        return response({
          ...saved,
          id: draftId,
          origin_handoff_id: handoffId,
        });
      if (path.endsWith("/handoffs") && init?.method === "POST")
        return response({ ...saved, id: handoffId, investigation_id: draftId });
      if (path.includes("/handoffs/"))
        return response({
          ...saved,
          id: handoffId,
          investigation_id: draftId,
          primary: selection(0),
          comparison: selection(1),
          note: "交接时的待确认事项",
        });
      if (path.endsWith("/investigations")) {
        if (init?.method === "POST") {
          saved = {
            ...saved,
            ...body,
            primary: body.primary ? selection(body.primary.offset) : null,
          };
          return response(saved);
        }
        return response({
          items: saved.version > 1 ? [saved] : [],
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
            saved.logs = body.logs.map((id: string) => ({
              source_log_id: id,
              state: "unverified",
              descriptor: { csn: "OTHER-CSN" },
            }));
        }
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
                ? [fail, pass]
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
      (b) => b.textContent === label,
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
it("explains project and stage before records, then expands SN beyond symptom filters", async () => {
  const v = await view();
  try {
    await v.click("查看项目 A");
    expect(v.host.textContent).toContain("测试环节");
    expect(
      v.requests.some((r) => r.url.pathname.endsWith("/observations")),
    ).toBe(false);
    await v.click("选择无线测试 · 无线工具");
    const start = v.requests
      .find((r) => r.url.searchParams.get("view") === "stages")!
      .url.searchParams.get("start");
    await v.click("查看该范围异常");
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
    await v.click("查看项目 A");
    await v.click("上位机活动");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    expect(v.host.textContent).toContain("失败涉及 SN 12");
    expect(v.host.textContent).toContain("趋势未取得");
    await v.click("查看项目 A");
    await v.click("查看该范围异常");
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
          (b) => b.textContent === label,
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
    await v.click("查看项目 A");
    await v.click("开始调查");
    const original = v.saved().context.start;
    await v.click("上位机活动");
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
    await v.click("查看项目 A");
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
    await next.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
    await v.click("上位机活动");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
    await v.click("选择无线测试 · 无线工具");
    await v.click("查看该范围异常");
    await v.click("选择异常 E1");
    await v.click("查看 SN-A 履历");
    await v.click("查看测试 2");
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
    await v.click("查看项目 A");
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
  const v = await view((url) =>
    url.pathname.endsWith("/observations") && url.searchParams.get("sn")
      ? new Response(
          JSON.stringify(page([fail, pass, { ...pass, status: "9" }])),
        )
      : undefined,
  );
  try {
    await v.click("查看项目 A");
    await v.click("查看该范围异常");
    await v.click("选择异常 E1");
    await v.click("查看 SN-A 履历");
    expect(v.host.textContent).toContain("原症状命中");
    expect(v.host.textContent).toContain("结果未知（9）");
    expect(v.host.textContent).toContain("通过 PASS");
  } finally {
    await v.dispose();
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
    expect(v.host.textContent).toContain("失败涉及 SN 12");
    failRead = true;
    await v.click("重新读取");
    expect(v.host.textContent).toContain("失败涉及 SN 12");
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
    await v.click("查看项目 A");
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
    await v.click("查看项目 A");
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
it("shows parent versus fresh readings, selected anomaly trend and version-record drill", async () => {
  const v = await view();
  try {
    await v.click("查看项目 A");
    expect(v.host.textContent).toContain("父视图读取");
    await v.click("查看该范围异常");
    await v.click("选择异常 E1");
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
