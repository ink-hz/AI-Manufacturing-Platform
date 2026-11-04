# 制造模拟源系统集成与物料交接发布

2026-11-04，已切换 https://agent.orbbec.com.cn/manufacturing 。本次上线两轮功能：**物料人工交接**（R06：发起→指定接收人确认→差异处理→受控取消，仅 OEM 项目可写入）与**模拟源系统集成**（SAP/WMS/MES/PDM/HR/OA/CRM/产测/PLC/客户/海外的类型化 mock 系统族：源操作、因果投递、消费回执、派生过账、BOM 同步、测试制品、BI 快照）。业务工作区织入约 58 个源系统业务步骤；对象详情新增只读来源证据（来源接受／消费送达／业务投影／SAP 过账分别显示）；意图恢复保持原操作身份——查询/继续沿用原 intent，源已提交或未知时不生成新执行 UUID，查询 NOT_FOUND（服务端未保存）解冻原草稿。

| 实际发布项 | 值 |
| --- | --- |
| 制造源码 | `f7a420b6e93890403d6b958523c18984ba95cdd9` |
| 平台源码 | `aff9cbd2b9d413ddee912c8773a0107c717cece3`（零平台文件变更，534 源／869 静态逐字节保留） |
| 镜像 | `sha256:d27f2e93e0ae7497d7a8beace0c62dc0b31f3b6b45474621ef096b73cf85c977`（基线镜像＋仅两个 COPY 层） |
| 切换后容器 | `ff7a4184dcd6a914bda327508738d5034bfe046e78da42ea51c0403a586c7bea`，healthy、重启 0 |
| 有序 Compose 输入 | 57→58，追加本次制造 overlay；其余 34 个容器与 Nginx 摘要保持 |
| 制造库 | schema21→23（前向迁移）；新增 9 张空表（material_handoffs 与 8 张 integration_*）；原 6 项目、45 SN、全部业务行逐表哈希不变；mock-systems 源库目录按需创建（切换后不存在） |
| 注册业务能力 | 81 项业务动作、34 类业务对象；集成动作需服务端分配的项目集成档案，交接写入仅限 OEM 模式项目——存量项目不自动获得 |

## 验证链

- **基线重放等价**：57 项输入＋纯净环境重建当前 API 全等（16 挂载／4 网络／112 环境键／65 HostConfig 字段）。为此对发布工具做窄幅扩展：重放映射器支持生产在用的 `propagation: rprivate` bind（其余传播值与未知选项仍 fail-closed），`bind_mount_spec` 八例专项测试，deploy 套件 173 通过。
- **本地全量**：后端 931 passed／35 项既有 opt-in 跳过；前端 34 文件 329 passed（含三条真实 React HTTP 页面旅程：订单与工程资料、补料与交接、生产测试到发运验收——旅程连续 5 次稳定）；bundle（TS/Vite/IIFE/作用域 CSS）通过；私有 E30 通过。
- **候选（隔离 Linux 容器、network none、只读根、UID10001）**：完整 36 场景 0 失败 0 未执行；OEM socket 流程通过（schema23、17 项新核心动作、事实表达标）；E29—E32 证据核验；归档 24562 份文件逐一哈希核对，SHA256 `086b660d8ea4b8ad3fdb866d047afc99d5b65b19c8fc095400b35e86120c3c57`，服务器与本地双份核对。
- **切换前回滚探针**：旧基线（642362d/schema21）经私有快照验证可重建（`readonly-schema-precutover.json`）；**切换后按 forward-only 策略旧源码不再是有效回滚目标**，保留实时库/WAL，修复一律向前。
- **切换前三库一致性备份**（legacy/workflow/authority，非跨库原子快照）。
- **切换后**：34 容器与 Nginx 不变；容器内域级校验（6 项目可见、205 份对象详情、54 页台账、平台管理员 81 动作、未授权成员拒绝、只读剥离，经真实目录策略回读，零业务写入）；公网 `/manufacturing` 200、健康 200、受保护接口匿名 401（private, no-store）；发布锁已释放。

本轮同时修复两处实证缺陷：①工作流层在 intent 持久化前拒绝后表单死角（查询 NOT_FOUND 现在解冻保留草稿）；②只读接口偶发 503 根因定位为 mock 源库别名守卫与 SQLite `-wal/-shm` 生命周期竞态（两次真实 trace）——改为单次原子 lstat＋副文件有界重观察，稳定别名仍拒绝，无业务写重试，8 例回归钉死。

## 边界与后续

本次为隔离模拟／人工凭据验证，不代表真实 ERP/MES/WMS 接口、设备采集或现场作业验收。**尚未交付、明确列为后续**：①线上三场景种子数据（Task6：种子 CLI 自包含打包、经哈希核验在 API 临时目录执行，真实 owner 复核后进行）；②候选内新家族旅程验收门（Task7：pinned Vitest 旅程进候选、TMPDIR 证据盘、sqlite_backup 集成库目录固定清单）；③员工浏览器实操与现场验收。两项继承债保留：共享壳窄屏账号名截断、旧 formHttp/oemFormsHttp act 警告。

实际维护入口为 `/opt/orbbec-agent-platform/staging/manufacturing-it-mock-20261104-r1/future-maintenance.json`（58 项有序输入）。schema23 为前向迁移，不可以 schema21 旧源码回退；恢复流程见[发布运行手册](runbooks/workflow-release.md)。发布工具箱与全部阶段收据保留于 `.superpowers/releases/manufacturing-it-mock-20261104/`（本地）与服务器 stage；首次 install 因误传 request.json 失败两次，产物完整清除后纯净重跑，全部失败输出按阶段保留（`*.failed-N`）。
