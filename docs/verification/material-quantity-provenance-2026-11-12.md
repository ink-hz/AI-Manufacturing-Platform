# T2数量来源契约与页面验证

日期：2026-11-12。依据：[确认记录](../reviews/2026-11-12-robot-oem-review-response-confirmation.md)、[TDD计划](../superpowers/plans/2026-11-12-material-quantity-provenance.md)、[T2任务书](../taskbooks/robot-oem/02-material-analysis.md)。功能代码截至`77e70c9`，本记录区分隔离验证与生产验收。

## 已实现的行为

料况原有数量旁新增类型化`quantities`：需求、到货、在途、合格、拒收、原始预留、缺口和有效覆盖均带来源方式、环境、数量性质、原对象/版本、时间和输入依据。收货、交出/实收、带数量的卡点及返回工单数量使用同一来源契约。原有标量和数量算法保留兼容；原生MES组件继续在独立表中观察，不进入平台余额。

页级`source_modes`直接从本页返回数量的完整输入集合派生，`source_modes_scope=returned_quantities`；空页不借用其他页来源。概览保留独立的`project_source_records`范围。来源输入不使用200条预览或501条扫描来冒充全量；更正、IQC确认、有效释放、历史需求关联及必要的共享批次占用保留各自身份。

页面在数字旁显示简短来源和依据时间，展开才创建输入明细DOM。模拟来源独立于“平台确认记录/观察记录”等数量性质，任一模拟输入不会被确认状态掩盖。新投影明确为null时显示未提供；旧接口没有投影时保留旧数字并标来源待核对。缺少范围字段的旧汇总不声称是本页数量来源，原始API标签也不自动解释为原生身份。

共享需求、交接及工单投影先核对项目内持久记录，拒绝不存在、跨项目及被修改的调用快照；交接来源、数量、指定接收、用途和归属不由调用方临时数据替代。现有项目授权、撤权、CAS、幂等、草稿与异步退役规则保持适用。

## 已执行验证

| 范围 | 命令或场景 | 结果及版本 |
| --- | --- | --- |
| 开发基线 | `test_material_control.py`＋`test_material_analysis.py` | 31项通过，8.36秒，`25467dd` |
| 纯来源模型 | `test_quantity_provenance.py` | 34项通过；十进制、来源/环境并集、mock保留、空输入、覆盖/时间及反序列化约束，`dec8866` |
| 后端关联回归 | 下方11文件命令 | 243项通过，69.62秒，`f4a9498` |
| 页面定向 | 来源组件、料况、上下文、MES、范围与实际WorkflowApp导航 | 72项通过，`c26f928`；最终中性观察文案和模拟观察展开39项通过，`77e70c9` |
| 普通页面回归 | `npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx` | 59文件、610项通过，`c26f928`；最终原目录结果在交付复核中补记 |
| 构建 | `npm run test:bundle` | `77e70c9`通过TypeScript、Vite、IIFE全局及CSS检查 |
| 实际宿主HTTP | E30受控岗位流程，回环HTTP＋jsdom | `77e70c9`为1项通过、3.34秒；使用既有宿主`70bf974d`，源配置由隔离测试进程清除 |

后端命令：

```sh
PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest tests/workflow/test_material_provenance.py tests/workflow/test_native_materials.py tests/workflow/test_quantity_provenance.py tests/workflow/test_material_control.py tests/workflow/test_material_analysis.py tests/workflow/test_supply.py tests/workflow/test_exchanges.py tests/workflow/test_material_handoffs.py tests/workflow/test_material_tasks.py tests/workflow/test_expedite_fulfillment.py tests/workflow/test_material_resolution_journey.py -q --tb=short
```

各开发任务记录了真实RED/GREEN和独立spec/quality审查。审查发现的数量模型不变量、共享函数持久化边界、旧接口范围及观察文案问题已分别复现修正并复审。页面集成断言在实现后补充的部分另做回归敏感性检查：将两项现有集成测试运行在隔离归档的`f4a9498`旧页面上，两项均按行为断言失败（旧数字99未变未知、缺少模拟标识），没有导入/环境失败；此记录不倒称为当时已执行TDD。

独立验收包括：

- `source_modes`与返回数量图逐项同源，包含工单、收货、交接和卡点；无关项目/页不会污染来源，必要的其他工单共享占用仍保留。
- 可复用`large_material_history(workflow, count=52)`建立两个隔离项目、52条需求和52笔交接，含不同单位、货主、版本与模拟尾项；搜索、尾页及输入图可达。它是后续M6待办测试的数据基础，**未修复M6的事项截断**。
- 206条相关收货、505条更正及超过501条项目来源记录；零差额更正和有效释放仍保留输入；不以预览数量代替依据数量。
- IQC按准确fact_id关联确认，更正按保留记录与哈希关联，释放按有效视图的完整键/哈希关联；读取前后数据库iterdump一致，重启、撤权、原生观察隔离均验证。

## 实际边界与后续

本轮只对平台持久记录的数量及依据形成可追溯投影；“记录完整”不等于外部库存、检验或现场流转全量。旧IQC行与后续确认无法证明首次产生方式时，保留本地引用和unknown，并分别保留确认身份；复杂历史批次可用性路径也明确unknown，不解除既有hold或改写余额。历史环境缺失不补成生产。

本轮没有访问真实SAP/MES/WMS源，没有源业务写入、连接允许清单变化或数据迁移。测试使用隔离数据库、FakeMes、MockRig/模拟权威及真实宿主回环HTTP；不代表生产同单闭环。浏览器、现场岗位走查和生产切换另行验收，生产源继续遵循[只读规则](../../AGENTS.md)。

M2解除重复登记、M1/M3料况内交接与直达、M6完整事项及M5 SAP真实契约mock仍按既定顺序接续；本次没有将这些修订标成已实现。

## 交付复核

整分支审查和原目录本地快进正在执行；最终提交、原目录测试、产物摘要及用户文件保全结果在验证后补记。代码合入与部署/生产验收分别记录。
