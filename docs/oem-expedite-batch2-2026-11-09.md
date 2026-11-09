# OEM 急料批次②③交付与数据流验证

日期：2026-11-09。设计、启动目标与任务书已按复审及用户“未打通系统使用 mock”的要求同步修订。

## 实现

- 里程碑只采用当前到货匹配及同工单、正实收、已签收/已解决的交接；更正旧匹配、其他工单、零实收和未解决争议不会冒充完成。
- 在办急料从开案起进入责任待办；production/supply 有正有效 IQC 合格量后显示“已检验”提醒。关案、撤权或只读后按现有授权协议过滤。
- issue.mark 追加打印/拣配/回执/过账四类人工状态事实，允许补录与重复；现有项目对象列表支持按 requirement_id 有界分页读取，不改账。
- 收货列表/详情显示关联在办急料标记，顺序、总数及分页不变。
- mes.shortage 通过既有源操作、MES→WMS 耐久消费及平台投影开案，来源显示 mes/mock；同投递、同源事实重复处理及关案后重放均不重复开案。
- schema 保持24，支持真实23升级与已有开发24库增量初始化。冻结夹具的197个数据库对象已独立与历史提交56e2c51逐项核对。

## 验证与证据

分主题专项验证：里程碑/责任待办72通过；发料标记/IQC/兼容231通过；MES欠料专项145通过、集成兼容343通过；preview专项25通过。最终全量：**1193 passed、35 skipped，零失败**（497.53秒），退出码0；结果记录在 `.superpowers/sdd/expedite-batch2/full-backend.log`。整分支独立审查通过，唯一证据格式小项已补齐。相同完整依赖环境下实际HTTP走查73步通过，退出码0。

实际回环 TCP HTTP 走查覆盖：项目→SAP/PDM资料→SAP需求→SRM承诺/到货预告→开急料案→观察→WMS收货→匹配→MES IQC→标记/待办→WMS上架/预留/拣配→精确对应的SAP过账子事实→双人交接→四状态登记→五里程碑→关案→MES欠料再开案→重复投影→重启读取。新增急料/issue/派生读取的前后快照检查工作流数量表、legacy authority表以及WMS/SAP源事实。

关键响应及实际服务地址保存在 `.superpowers/sdd/expedite-batch2/e2e-walkthrough.md` 和 `http-evidence.json`。中间失败记录保留于同目录的各次运行子目录，不以修改前置条件消除失败。可重跑脚本为 `scripts/verify_expedite_batch2.py`：

```sh
PYTHONPATH=src /Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python scripts/verify_expedite_batch2.py --help
```

执行时指定一个尚不存在的 `--root` 绝对目录、现有 Agent 平台源码 `--platform-root` 和位于preview目录之外的 `--output`。脚本准备私有 demo、启动/停止实际服务并保留结果。旧数据不会重新播种。preview 的 `--actor-id` 只允许该私有清单内的合成身份，项目权限仍真实校验。

## 验收边界

本轮平台、数据库、授权、幂等与 HTTP 服务真实运行，未连接的外部系统是类型化 mock。源接受、消费送达、业务投影和 SAP 过账各有独立证据；IQC 合格不代表已上架，人工 posted 标记不代表真实 SAP 过账。I1 的真实采购/在途字段、客户供料来源及生产只读接入仍按[接口契约](material-dataflow-interface-contract-2026-11-09.md)核实。本轮不修改前端，不部署，不进行真实外部系统调用或 L3 写回。
