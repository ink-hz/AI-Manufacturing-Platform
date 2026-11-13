# Mac SAP只读中转 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 线上制造平台经本Mac查询真实SAP测试工单、组件和MRP。

**Architecture:** 固定只读RPC网关+SSH反向Unix socket+延迟构造云客户端。来源双层指纹钉定；业务快照/权限继续使用现有工作流。

**Tech Stack:** Python3.11、stdlib HTTP/Unix sockets、现有FastAPI/Pydantic、OpenSSH、macOS launchd、现有Compose发布流程。

## Global Constraints

- 根AGENTS生产源只读持续有效，本任务SAP测试环境也只读；不得放宽原生函数或生产环境允许范围。
- SAP凭据只在Mac私有配置；令牌/原始业务证据不入Git、参数或公开日志；不得开公网代理/端口。
- 用户已批准并要求开始，连续实施。保留根目录三处用户修改。
- 协议/配置/上限严格以spec为准；不做通用转发或源请求重试。Mac离线仍保留成功快照及原读取时间。
- 只在现有部署流程内切换API；共享Nginx及其他容器不改。

### Task 1: 固定Mac只读网关

Files: `sap_access/relay_protocol.py`, `relay_gateway.py`, tests `tests/sap_access/test_relay_gateway.py`。

Interfaces: spec精确请求/响应；`build_gateway(config_path,audit_path,token_path,*,port=0,service=None)` 返回仅127.0.0.1的HTTP server；service测试注入，默认原生SapAccessService。CLI `python -m manufacturing_platform.sap_access.relay_gateway --config <private> --audit <private> --token <private> --port <int> --ready <private>`；ready包含pid/port/generation，不含业务或凭据。

- [ ] TDD：先证明缺失实现RED；测试认证前无源调用、重复/额外字段、2048限制、拒绝未知方法/URL/函数、原生参数校验、来源变化阻止调用、固定结果/错误、并发上限、无密钥/业务日志。
- [ ] 实现共享协议校验、token安全读取、固定操作派发，正常查询传入真实expected_fingerprint；describe不触SAP网络。
- [ ] CLI绑定环回，ready原子写入0600，正常信号退出只清理自己的ready。源service.audit沿用原有规则。
- [ ] 运行网关及原生SAP相关测试，提交本任务文件，独立评审。

### Task 2: 云端Unix只读客户端与产品状态

Files: `sap_access/relay_client.py`, `relay_worker.py`, `selector.py`, `__init__.py`; `workflow/sap_materials.py`; `webui/.../SapMaterialBrowser.tsx`及相关测试。

Interfaces: `build_sap_access_service`构造无I/O，selector兼容原有service方法。relay配置精确字段见任务brief；`read_context`本地返回真实expected_source+cloudbinding；查询验证cloudbinding并向Mac传expected_native_fingerprint，严格校验RPC响应与作用域，独立worker硬截止70秒/2MiB。

- [ ] TDD：Unix真实socket回环测试、鉴权/来源/请求ID/作用域不符拒绝、配置切换、70秒硬截止可注入短期测试、超限/断线、审计先于I/O且不保存原文、factory构造无I/O、旧native模式回归。
- [ ] 实现严格私有配置loader/selector、固定RPC客户端及worker；unsupported诊断操作明确拒绝，不伪造SAP鉴权或数据成功。
- [ ] workflow安全错误白名单与中文Mac离线提示；保存读取时间/旧结果行为不改变，前端补真实错误呈现回归。
- [ ] 运行相关SAP/workflow/前端测试与构建，提交本任务文件，独立评审。

### Task 3: Mac服务、受控隧道与线上发布

Files: `scripts/sap_relay_supervisor.py`, 测试及文档；私有部署目录不入Git。

Interfaces: supervisor读取0600私有settings（SSH目标/key/known_hosts、gateway ready/token、远端固定目录），每次唯一socket，经describe真实性/权限验证后切换active.sock；不记录密钥、业务内容，不转发源写方法。

- [ ] TDD supervisor启动/退出/重连与仅清理自己socket；固定目标、没有任意命令注入；注入fake进程验证，不接SAP。
- [ ] 建立固定代码/独立运行环境、私有配置/令牌及LaunchAgents；云私有目录按UID10001设置，反向socket与active指针不暴露公网。
- [ ] 真正从云以及API容器UID10001读取Mac describe，再读一个既有测试工单和首组件MRP；保留完整私有证据、脱敏计数与停止条件，验证Mac断线保留快照。
- [ ] 完成整分支评审和主线归并；按现有安全发布捕获实际Compose、准备精确candidate、隔离验收及前向兼容rollback，受控API切换；真实线上后台读取/健康/其他容器静态与源写入为0验收。
- [ ] 同步可停用/恢复路径和实际发布版本；明确未做员工浏览器验收，不伪造员工身份。
