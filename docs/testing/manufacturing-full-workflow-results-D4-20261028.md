# 制造全流程本地候选验收记录 D4

2026-10-29（Asia/Shanghai）。最终合成结果：**36 passed / 0 failed / 0 blocked / 0 not_executed**。原始全量执行为28通过/8失败；修复后仅复跑受影响8例。这里是逐例版本明确的合成验收，不是一次在最新提交上重新执行的全量通过。原[验收矩阵](manufacturing-full-workflow-acceptance.md)数量和完整流程保持不变。

本地代码与真实 HTTP/SQLite/PF 宿主验证已完成；外部业务系统和身份提供方位于明确模拟边界。**尚未部署**，浏览器视觉、真实 ERP/MRP/MES/财务、员工多角色及生产业务验收未执行。R1仍须在准确集成源码及实际隔离运行镜像中，以私有 Linux Node/锁定依赖及两个历史源码导出，再执行一次 network-none 全36例；本报告不替代该门禁。

## 源码、构建与数据

- 原始完整36例：MF `a7ddabdec2f03e9ca7cba3fc548bf1c4fc9ae023`，PF `74c7e6b4307946e77147039e42e3b6c38019bc12`。
- 修正8例：MF `8e253f87a899454fc0211ce16bbce2ed89372668`，PF相同。仅5个测试/夹具文件变化；无领域/宿主生产代码、共享 CLI 初始化或时钟实现变化。两轮提交状态均只有原有未跟踪 node_modules 符号链接，PF干净。
- 种子 `20261028`，配方 `workflow-complete-v1`，业务时钟 `2026-10-28T00:00:00Z`，每例独立 `test` 数据集。E07显式在T−2d建立当时有效库存，按可信构造器业务时间重启到T，证明其过期；安全/登录时间仍为真实UTC。
- Python3.11.15、SQLite3.53.4、FastAPI0.141.1、Pydantic2.13.4、Starlette1.3.1、Uvicorn0.52.1，macOS26.4 arm64；Linux运行镜像验收另属R1。
- JS SHA256 `acae04a49d6cc3e2ea26c553279438c898530d6eb7d05b7474e7f06cabf5bfb0`；CSS `45605e1e32940ce214d1db817ec883d9c4e404a977e26b83a6c8ec3fd03602b4`。最终重新构建字节与原始全量使用的制品相同。
- 完整连续手册 SHA256 `8966c7d91be4387b67271449d1c25b3214a7587a149c26c40c3a39dd035e2dfd`；没有截断、替换或导入并行用户草稿。
- 逐例源码文件内容映射摘要、源码/制品联合摘要、实际tree状态、原始manifest/result摘要及完整证据目录见[机器可核对清单](manufacturing-full-workflow-results-D4-20261028.json)。本报告的后续文档提交不改写任何旧运行的源码身份。

## 36 个独立场景结果

A为原始全量运行 `run-20261028T194603-344de64f9fe64beb896b15a3cadbc12a`，B为已提交修正复跑 `run-20261028T195539-dcafaf8efc8e40899df1385379aad561`。A证据根 `/private/tmp/manufacturing-workflow-20261028-D4-first/run-20261028T194603-344de64f9fe64beb896b15a3cadbc12a`；B证据根 `/private/tmp/manufacturing-workflow-20261028-D4-committed/run-20261028T195539-dcafaf8efc8e40899df1385379aad561`。每行目录下的 `result.json`、`manifest.json`、编号请求/响应和只读DB快照可核对；E29/E31/E32含实际 `d3-proof.json`/transitive artifact index，E30含实际React运行证据。

| 场景 | 结果 | 运行/源码 | 耗时ms |
|---|---|---|---:|
| E01 | passed | A / a7ddabd | 641 |
| E02 | passed | A / a7ddabd | 853 |
| E03 | passed | A / a7ddabd | 827 |
| E04 | passed | A / a7ddabd | 1128 |
| E05 | passed | A / a7ddabd | 715 |
| E06 | passed | A / a7ddabd | 960 |
| E07 | passed | B / 8e253f8 | 1559 |
| E08 | passed | A / a7ddabd | 1262 |
| E09 | passed | A / a7ddabd | 1269 |
| E10 | passed | A / a7ddabd | 891 |
| E11 | passed | A / a7ddabd | 1078 |
| E12 | passed | A / a7ddabd | 798 |
| E13 | passed | A / a7ddabd | 986 |
| E14 | passed | A / a7ddabd | 980 |
| E15 | passed | B / 8e253f8 | 889 |
| E16 | passed | A / a7ddabd | 4261 |
| E17 | passed | B / 8e253f8 | 901 |
| E18 | passed | A / a7ddabd | 803 |
| E19 | passed | A / a7ddabd | 889 |
| E20 | passed | A / a7ddabd | 1014 |
| E21 | passed | A / a7ddabd | 4423 |
| E22 | passed | A / a7ddabd | 1012 |
| E23 | passed | A / a7ddabd | 904 |
| E24 | passed | A / a7ddabd | 1422 |
| E25 | passed | A / a7ddabd | 581 |
| E26 | passed | A / a7ddabd | 1237 |
| E27 | passed | B / 8e253f8 | 790 |
| E28 | passed | B / 8e253f8 | 703 |
| E29 | passed | B / 8e253f8 | 7107 |
| E30 | passed | A / a7ddabd | 1600 |
| E31 | passed | B / 8e253f8 | 17337 |
| E32 | passed | B / 8e253f8 | 8486 |
| F01 | passed | A / a7ddabd | 11861 |
| F02 | passed | A / a7ddabd | 3496 |
| F03 | passed | A / a7ddabd | 1999 |
| F04 | passed | A / a7ddabd | 4365 |

## 首错、修复与回归

首轮E07的夹具错误重定义物料所有者；修正使用另一客户项目的真实同料号库存与真实提前入库后过期库存，分别证明范围/所有权隔离与过期拒绝，合格库存余额不变。E15只有已接受的试产开工，需全范围恢复；改用真实试产需求语义定位，不依赖UUID列表顺序，并证明原计划拒绝、2/1/1缺口、补货/新计划/恢复回执、原SN和版本历史。E17按真实冻结规格校验要求422，且缺失/改宽限值不生成测试/PASS、不改变原规格。E27核对过期版本的持久拒绝事件与不变的当前冻结，不把无效回执冒充已接受回执。E28使用实际交换来源身份，在总量相同/明细键不同的条件下产生有责任人的差异，不改变已接受80。E29/E31/E32首轮实际子证明成功，但父验证拒绝macOS /tmp符号链接；规范路径复跑，安全规则不变。

E15所有中间错误亦保留：第一次修正仍按数组位置选中满额bulk，随后证据断言误用了不在value中的id、仅在DB历史中的interrupted_plan_id。最终从当前计划选择trial/WO/material、携带外层ID，分别核对API当前plan与数据库原中断plan，没有重试失败动作或降低业务断言。首轮与四次选例复跑、最后提交复跑全部独立目录；原失败未覆盖。

| 验证 | 真实结果 |
|---|---|
| MF完整Python工作流+旧功能 | 首次636通过/1失败/36有意排除，181.59s；唯一旧预期把规范化来源mes当成MES。修正后影响预览+来源身份/历史18通过，3.40s。其余636首次通过保留，不冒称第二次全量637通过。 |
| MF完整组件 | 最终235通过/20文件，13.47s；仅排除必须由CLI拥有宿主的E30私有组件测试，E30已实际通过。真实HTTP表单夹具补齐owned manifest/dataset，2条真实链路单独通过。 |
| MF构建/制品 | TypeScript+Vite86模块+IIFE/CSS边界检查通过。 |
| PF真实MF桥接/授权 | 1074通过/0跳过，31.99s；启用TEST_MANUFACTURING_RELEASE_ROOT指向实际已构建MF。 |
| PF宿主/导航/授权/手册组件 | 195通过，实际手册另1通过，最终196覆盖/0未执行；首次缺环境跳过的手册已补验，不算基线跳过。 |
| PF构建 | 通过；保留既有大于500kB chunk提示。 |

MF Python有意排除的是已由CLI执行的 `tests/workflow/test_acceptance.py::test_f01`—`test_f04`、`test_e01`—`test_e32`，共36个重型包装；同文件的runner单元测试仍执行。排除不算通过或基线跳过。首轮MF通用UI失败输出保留；旧启动清理移除了最初无manifest的临时目录，仅日志保留，此限制明确记录。修正后的启动错误会保留去除secret后的目录。

PF139条警告全部来自既有 `backend/tests/test_dingtalk_auth_api.py` 向 Starlette testclient.py:454传每请求cookies的DeprecationWarning。该测试文件与实际旧部署PF22f65f19字节一致，最新修改提交619f54a；未抑制，也不声称输出无警告。可选F401检查发现未改动的scenario模块已有unused subprocess导入，保留供全分支检查；F821/F841及git diff --check通过。

完整命令、原始日志、所有错误链、实际变更与验证账本保留于工作树 `.superpowers/sdd/task-D4-report.md`，这些运行材料不进入发布包/Git。

## 身份、旧数据和实际运行边界

实际请求使用服务器会话cookie、Origin/CSRF与当前角色/资格；实际PF宿主只在外部身份提供方和只读合成grant仓库处使用测试边界，不使用调用者role headers或员工会话。权威mock保存库存、预留、冻结、开工与发货回执；超时后查询幂等恢复。成本关闭登记签署的模拟ERP凭据及SHA，未生成真实会计凭证。测试私有入口不装入生产业务包。

E32通过真实旧API创建7个独立合成旧项目，操作、任务和工程包均真实持久化；新工作流和仅自有数据重置前后全部10个存在的旧表行数/内容摘要完全一致，逐表值在JSON清单。它们不是生产的7个项目。E29的ACL/资格撤销、E31实际宿主重启/新会话、E32标签均包含实际React或真实进程证据。历史来源为A1 b7397b4c0acd2bb9d32cafade8e885e4b9e7c732与legacy ec41b39bdf8c0b5cc6b0193ed646a44050106ca3；历史源码API已证明，旧编译资产缺失且不声称已证明。

根控制器提供2026-10-28T19:37:32Z只读实际运行基线：容器4c27bc95，镜像3a1b7d5，实际MF19b58607/PF22f65f19，healthy、restart0；42项Compose输入、15个mount、29个其他容器。13张旧表的完整计数/摘要及基线文件SHA在JSON清单；manufacturing_projects=7、project_operations=25、数据库检查ok，未发生本功能部署。生产基线不是D4主动重新访问所得，发布前仍需根控制器复核。

候选新增工作流独立DB/权威状态DB、显式dataset配置和schema16兼容迁移；这些配置与实际老发布配置需在R1分别核对，不能从本地通过、Git提交或HTTP200推断线上启用。现有共享Nginx/Office/其他容器未由本任务修改；实际挂载、权限、隔离、schema和配置差异由发布流程核对。并行目标架构草稿不作为已实现声明。

## 完整证据存储测量

首轮完整36选择实际产生161,168,427逻辑字节、232,194,048分配字节。最终36个被采用案例的完整原始证据合计23,465文件、160,231,885逻辑字节、231,038,976分配字节；没有裁剪/压缩代替原始证据。

全部保留的首轮及选例复跑合计282,667,556逻辑字节、392,859,648分配字节；逐目录容量在JSON。此为macOS文件系统实测，Linux allocation/运行临时峰值另需实测；R1必须按完整证据及源码/历史导出提供可写容量并预检，不以扩大预算或截断证据掩盖失败。上述路径为本地持有证据，最终发布归档由根控制器处理。
