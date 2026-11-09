# 物料主线数据流与接口验证契约

日期：2026-11-09。依据：[启动目标](platform-development-launch-plan-2026-11.md)、[总体架构 §7.6](manufacturing-platform-architecture.md)、[急料任务书](superpowers/specs/2026-11-09-oem-expedite-batch2-tasks.md)。用户授权未打通的系统使用 mock。

## 本轮运行边界

平台使用 `scripts/preview_manufacturing.py` 启动实际 FastAPI/SQLite 回环服务，验证脚本以 httpx 发送真实 TCP HTTP 请求。SAP、WMS、MES、PDM、SRM 等尚未连接的外部系统使用既有类型化 mock 源、独立源库、耐久 outbox/inbox 和因果回执。来源保留 `mode=mock`，人工观察保留 `mode=manual`；不把 mock 接受当作外部生产系统成功。

唯一非 HTTP 维护步骤：新项目创建后、任何业务意图前，由已有服务端维护函数绑定不可变 `oem-network-v1` demo 档案。业务数据、权限授予、源操作、投影、交接、发料标记和关案均走 HTTP，不直接插入业务行。切换预览合成身份仅限私有清单，项目权限继续校验，双人交接不改为同人确认。

## I1—I5 对应事实

| 接口 | 本轮 mock 验证链 | 权威语义及未覆盖边界 |
| --- | --- | --- |
| I1 供料计划/在途 | SAP `plan`→`purchase_requirement`→SRM `promise`→`arrival`→WMS `receipt` | 验证需求、承诺、预告和受控收货的因果关联。SAP 正式采购订单/在途字段尚待真实契约核实，不能把本样本称作已连接 SAP 采购事务。客供计划来源须由客户确认，SRM 此处只是合成协同源。 |
| I2 收货/过账 | WMS `receipt`→SAP `receipt_posting`；WMS `pick`→SAP `accounting_entry` | 查精确 cause 对应的 SAP 子事实及 posted_at；WMS 原事实上的 sap_posted=null 不等于失败，也不等于已过账。 |
| I3 仓储作业 | WMS `receipt`→`qualification`→`putaway`→`reservation`→`pick` | 收货、合格、上架、预留和线边移交各自有来源。平台人工 issue.mark 是状态声明，不生成任何 WMS/SAP 作业。 |
| I4 IQC | WMS `receipt`→MES `iqc`→WMS `qualification` | 合格/拒收量带单位精度与原始收货身份；正有效合格量只触发“已检验”责任提醒，不证明上架完成。 |
| I5 欠料/急料 | MES `shortage`→WMS 耐久消费回执＋平台 material_expedite 投影 | 与人工开案共用生命周期、OEM/归属/在办唯一约束；WMS 消费只确认接收欠料信息，不产生库存或调拨。 |

## R13 七项验证

| 项目 | 本轮契约 |
| --- | --- |
| 身份与授权 | 合成身份来自私有 preview 清单，业务仍经项目角色、OEM、CSRF、CAS 与实时授权；生产凭据与真实 endpoint 不在本轮配置。 |
| 对象范围 | requirement→commitment→receipt→IQC→同工单有效交接。当前匹配才能贡献到货里程碑；共享批次不得串用其他工单。 |
| 成功含义 | HTTP200、源接受、消费送达、平台投影及 SAP 过账分别记录。查询 pending 意味着还需推进耐久投递，不能直接改为成功。 |
| 幂等 | command operation_id、事实 source key、投递身份分别沿用原协议。同事实重放不重复开案；关案后重放旧源不重开；不同事实碰到已有在办案仍拒绝。 |
| 异常处理 | 校验、权限与在办冲突按既有业务/源回执协议返回；源事实/回执不可覆盖。未知或未送达明确保留，不以放松前置条件通过联调。 |
| 对账方式 | 按 source key/cause 查原事实与回执，按同需求链查对象，按账表快照证明急料/issue/待办不改账；记录发料四状态、有效里程碑、关案清理和重启读取。 |
| 责任人 | 本轮软件与 mock 验证由 Neo/Codex 实施；真实 SAP/WMS/MES/客户源的负责人、授权与现场口径仍须由启动计划中的 IT/业务接口会确认。 |

## 真实系统切换门槛

逐接口确认来源身份与授权、外部单据到内部对象的映射、原始事实留存、发生/采集双时间、历史导入、增量游标与重启恢复、异常/对账责任、人工停录与回退方案。保留现有 demo/test 守卫；真实只读接入另经服务端可信组合，不能开放 mock 源操作或 L3 写回来冒充连接。

本地 HTTP 走查的命令、实际地址、来源、关键响应和退出结果落在 `.superpowers/sdd/expedite-batch2/e2e-walkthrough.md` 及同目录 `http-evidence.json`。该证据属于软件数据流验收；真实外部接口、真实客户数据和现场业务样本分别验收。
