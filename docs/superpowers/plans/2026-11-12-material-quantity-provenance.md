# T2数量来源契约实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每项料况数量均能说明来自哪里、适用哪个对象/环境、何时取得以及使用了哪些输入；模拟和未知身份不会被平台确认或分页掩盖。

**Architecture:** 增加只读的类型化数量投影，旧标量与既有数量算法保持兼容。纯来源模型、持久事实读取和页面展示分别负责合并规则、准确输入及岗位可读标识；页级汇总从返回的逐项投影派生。MES组件保留独立观察表。

**Tech Stack:** Python 3.11 / Pydantic / SQLite / FastAPI；React 19 / TypeScript / Vitest。

## Global Constraints

- 生产MES/WMS、SAP/MRP只读；本项不调用源系统，不更改生产允许清单、写权限、MRP执行或业务适配。
- `origins`取全部输入的去重并集；任一模拟输入使派生结论持续标为模拟；平台确认不能掩盖mock来源。
- `environments`取全部输入的去重并集；未知环境保留unknown，不从系统名、项目名或SourceRef.mode推定production。
- `SourceRef`既有写入模型与历史记录不改；不新增可由普通客户端自报“生产/可信”后绕过准入的字段。
- 原生MES组件观察不得并进平台确认余额；库存、合格、预留、已提料、实收保持原语义，现有数量算法不改。
- 旧标量保持原值；新增`quantities`是同一数量的来源投影，不提供另一个修改数量入口。未知数量为null；已知数值但来源不全保留数值并明确未知身份。
- 所有事实读取先按项目授权与数量的真实适用范围筛选；来源输入不从200条预览或501条扫描上限推断完整。
- 页级`source_modes`与返回的逐项身份从同一投影派生；增加明确范围，空页不冒用其他页的来源。
- 历史更正、正式准入、预留释放、批次冻结/有效期及共享占用须保留实际影响数量/判断的输入身份；缺失来源显式unknown。
- 已有CAS、幂等、草稿、项目/用户/API退役隔离及撤权行为继续有效。
- 不实现M2任务扩展、M1/M3导航、M6完整事项或SAP mock；本轮提前建立51+及跨项目的测试数据，交给后续任务复用。

## 验收依据与工作区

[已确认的评审处置](../../reviews/2026-11-12-robot-oem-review-response-confirmation.md)、[专项spec第4/7节](../specs/2026-11-12-sap-mrp-contract-mock-design.md)、[T2任务书](../../taskbooks/robot-oem/02-material-analysis.md)。用户已明确“改完之后开始吧”，本计划在当前会话连续执行。

隔离目录：`/Users/neo/.codex/worktrees/4ce0/AI-Manufacturing-Platform`，分支`codex/oem-quantity-provenance-20261112`，基线`25467dd`。根AGENTS规则已核对；原目录预映像保存于受控临时文件。现有料况基线31项通过。

执行Python：`PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest ...`。前端在`webui/`使用已安装依赖。逐任务提交和独立审查，最终整分支审查后核对原目录预映像并本地快进，不推送或部署。

## 文件与契约

- `quantity_provenance.py`：纯模型和来源/环境/覆盖/时间合并，不读数据库。
- `material_source_reader.py`：按项目读取原SourceRef、确认/更正、预留回执和正式投影，给出单个输入的身份；不写数据。
- `material_provenance.py`：按既有余额的范围组合输入，负责需求、收货、交接数量；新文件各保持职责单一。
- `material_control.py`：在原事务内附加数量投影与页级来源；`native_material_service.py`附加独立MES组件身份。
- `materialControl/QuantityValue.tsx`和类型：简短来源提示及按需展开依据，供既有料况/流转/MES组件表复用。

新增JSON契约（Python模型/TS类型字段一致）：

```python
class QuantitySource(StrictModel):
    reference: str                 # 稳定且含项目/对象/版本/数量含义的引用
    project_id: str
    object_kind: str               # 本地对象类别
    object_id: str
    system: str | None
    source_type: str | None        # 原SourceRef.object_type
    external_id: str | None
    version: int | str | None
    namespace: str | None
    origin: Literal['native', 'manual', 'file', 'mock', 'unknown']
    environment: Literal['production', 'test', 'development', 'mock', 'unknown']
    occurred_at: AwareDatetime | None
    collected_at: AwareDatetime | None
    coverage: Literal['complete', 'partial', 'failed', 'unknown']
    value: str | None
    unit: str | None
    meaning: str

class ProvenancedQuantity(StrictModel):
    value: str | None
    unit: str
    meaning: str
    origins: list[Literal['native', 'manual', 'file', 'mock', 'unknown']]
    environments: list[Literal['production', 'test', 'development', 'mock', 'unknown']]
    fact_role: Literal['confirmed', 'observation', 'unknown']
    observed_at: AwareDatetime | None
    collected_at: AwareDatetime | None
    coverage: Literal['complete', 'partial', 'failed', 'unknown']
    source_refs: list[QuantitySource]
    input_refs: list[str]
```

字段附加到`requirement.quantities`、`receipt.quantities`、`handoff.quantities`及`mes_component.quantities`，键为原数量字段名。映射中每项值都包含完整投影。已签收量使用handoff中的`received_quantity`键；未签收量为null，不把未签收冒作已收0。

### Task 1: 纯数量来源模型与合并规则

**Files:** Create `src/manufacturing_platform/workflow/quantity_provenance.py`；Create `tests/workflow/test_quantity_provenance.py`。读取`contracts.py`的`StrictModel`/`SourceRef`，不修改其写入契约。

**Interfaces:**

```python
def source_from_ref(source, *, reference: str, project_id: str,
                    object_kind: str, object_id: str, value: str | None,
                    unit: str | None, meaning: str,
                    environment: str = 'unknown', namespace: str | None = None,
                    trusted: bool = False
                    ) -> QuantitySource: ...

def quantity(value: str | None, unit: str, meaning: str,
             sources: list[QuantitySource], *, fact_role: str = 'confirmed',
             coverage: str | None = None) -> ProvenancedQuantity: ...

def source_modes(quantities) -> list[str]: ...
```

`source_from_ref`只接受既有SourceRef/其字典/null；mode api只有`trusted=True`（调用方已核对持久准入/绑定）才映射origin native，否则unknown。其他已知mode保留原义，缺失/无效身份为unknown；可辨认的mock标志不能因其他元数据损坏而丢失。mock环境为mock；其余环境只有`trusted=True`且调用方有持久可信绑定时才能使用，否则unknown。未知或朴素时间不补当前时间。原始SourceRef不能从其自身的字符串证明trusted。

- [ ] **Step 1: 先写独立失败测试。** 构造同项目manual输入和mock输入，各给不同时间、稳定引用和十进制字符串；验证混合数量origin/environment并集、mock持续标识、input_refs与去重source_refs一一对应、null不转0、Decimal字符串不经float、输入不被改写。增加无来源、缺时间、同引用不同内容、重复来源以及未知环境测试。

```python
def test_mock_identity_survives_platform_confirmation():
    from manufacturing_platform.workflow.quantity_provenance import quantity, source_from_ref
    inputs = [source_from_ref(
        dict(system='sap', object_type='plan', external_id='synthetic-plan',
             version=1, mode='mock', occurred_at='2026-11-01T00:00:00Z',
             collected_at='2026-11-01T00:00:01Z', evidence='isolated test'),
        reference='p/requirement/r/required/1', project_id='p',
        object_kind='requirement', object_id='r', value='20.001', unit='kg', meaning='required')]
    result = quantity('20.001', 'kg', 'required', inputs)
    assert result.origins == ['mock'] and result.environments == ['mock']
    assert result.fact_role == 'confirmed' and result.value == '20.001'
    assert result.input_refs == [inputs[0].reference]
```

- [ ] **Step 2: RED**：`... -m pytest tests/workflow/test_quantity_provenance.py -q --tb=short`；记录导入/行为失败，确认是缺少功能。
- [ ] **Step 3: 实现模型及纯合并。** 使用集合并集排序、完整来源引用去重；同引用不同内容拒绝，不能静默覆盖。覆盖保守排序failed→partial→unknown→complete；显式coverage只能降级。时间取全部输入中最早值，任一必要输入缺时间则对应汇总时间为null。空输入origins/environments各为`['unknown']`、role为unknown、时间为null、coverage至多unknown，source_refs/input_refs保持空；不要伪造来源引用。`source_modes`从origins派生，native映射旧值api，其他值原样，空数量集合返回空列表。数量与输入value仅接受有限的普通十进制字符串/null，保留符号、前导零和精度，不接收科学计数或NaN。
- [ ] **Step 4: GREEN**：同一命令通过；序列化再读回保持字段/小数/引用和不变量。模型验证不得允许手工构造投影删除mock输入身份。
- [ ] **Step 5: Commit**：仅提交上述两个文件；报告RED/GREEN命令、输出和自审。

### Task 2: 按实际数量范围附加持久来源，提前准备大集合

**Files:** Create `src/manufacturing_platform/workflow/material_source_reader.py`、`material_provenance.py`；Modify `material_control.py`、`material_control_models.py`、`native_material_service.py`；Create `tests/workflow/test_material_provenance.py`、`tests/workflow/material_provenance_fixtures.py`；Modify `tests/workflow/test_material_control.py`、`test_native_materials.py`（需要新断言时）。

**Consumes:** Task1模型与`quantity`、`source_from_ref`、`source_modes`。不改`supply._page_balances`/`material_analysis.analyze`数量算法。

**Produces:**

```python
def requirement_quantities(tx, project_id, rows, balances, unknown_quality):
    # returns dict[requirement_id, dict[quantity_field, ProvenancedQuantity]]
    ...
def receipt_quantities(tx, project_id, receipt_id):
    # returns dict[quantity_field, ProvenancedQuantity]
    ...
def handoff_quantities(tx, project_id, handoff):
    # returns dict[quantity_field, ProvenancedQuantity]
    ...
```

内部读取函数可按职责划分；对外仅暴露这些只读投影。单次事务缓存项目内来源，按批查询，避免每个数量重复全库扫描。需要的上下文见`.superpowers/sdd/quantity-provenance/design-audit.md`，其中以实际代码为准核对既有歧义判断。既有数量范围至少包括：

| 数量 | 必须追溯的输入 |
| --- | --- |
| required | 当前/显式历史需求与对应计划、工单身份；保留需求范围 |
| received / in_transit | 与余额相同的lineage＋工单＋物料＋货主＋单位＋精度范围，当前承诺、有效收货及相关更正 |
| qualified / rejected | 同范围有效IQC原记录、准确正式确认以及实际更正；人工检验与源确认身份分开保留 |
| reserved | 同范围实际authority回执和integration投影、有效释放；不把人工“请求”当确认 |
| shortage / confirmed_satisfied | required、有效预留和用于可用性/质量/归属判断的输入；冻结、有效期、共享占用等证据可追问；确认不足时保留原null |
| receipt quantities | 原收货、IQC、正式确认及更正；uninspected包含收货与已检输入，不只取receipt.source |
| handoff quantity / received_quantity | 实际交出声明、指定人签收声明及用途核对；交出与实收各自身份，未签收为null |
| MES required_quantity / withdrawn_quantity | 原生绑定环境/namespace＋工单/组件键＋快照；role=observation，发生时间无证据则null，collected_at用持久快照；已提料未知仍null |
| issue.quantity | shortage沿用需求shortage；待检沿准确收货uninspected；短收沿实际交出/签收和既有独占补收组，引用完整关联证据；找到数量不当作实收 |

本地人工检验无SourceRef时用其实际操作者/记录引用和持久created_at声明manual；发生时间不假装已知。IQC源确认必须以project＋fact_id匹配本次IQC，不能按receipt.object_id把全部确认附给每次检验。预留从已保存exchange.mode/接受回执及integration来源取身份，释放只收集与integration_projections全键/哈希匹配、实际影响有效数量的事实。更正必须保留其delta、exchange和实际来源；解析不到保留本地引用及unknown，不能借用原收货来源。缺失来源标unknown。不要仅凭system=sap或api推定生产，不用fixture命名判断mock。

可用性依赖涉及所有相同批次的有效占用、冻结/有效期、物料移动/库存核实输入。复杂历史路径不能重建来源时，保留明确本地eligibility引用和unknown/coverage=unknown，不宣称完整正式生产判断；不改变既有hold。数量输入图可说明“平台持久记录范围完整”，不声称外部库存/检验全量。

- [ ] **Step 1: 写API失败测试和可复用大集合fixture。** 通过业务API建立需求、收货、检验、任务/交接；大量历史记录可用明确的SQLite克隆构造，但不能用SQL伪造生产验收。fixture至少两个项目、单项目52条需求/51+物料任务或交接，另有不同单位/货主/版本；后续M6可直接复用。受控合成mock来源必须在测试中明确标注。

```python
def test_page_modes_are_derived_from_returned_quantity_identities(workflow):
    from .conftest import BASE
    project, req, _ = workflow.material_requirement(mode='oem')
    response = workflow.client().get(f"{BASE}/projects/{project['id']}/material-control")
    assert response.status_code == 200
    page = response.json()
    values = [q for row in page['requirements'] for q in row['quantities'].values()]
    values += [q for row in page['receipts'] for q in row['quantities'].values()]
    values += [q for row in page['handoffs'] for q in row['quantities'].values()]
    values += [q for row in page['work_orders'] for q in row['quantities'].values()]
    values += [issue['quantity_fact'] for row in page['requirements'] for issue in row['issues'] if issue.get('quantity_fact')]
    expected = sorted({'api' if origin == 'native' else origin for q in values for origin in q['origins']})
    assert page['source_modes'] == expected
    assert page['source_modes_scope'] == 'returned_quantities'
    assert next(r for r in page['requirements'] if r['id'] == req['id'])['quantities']['required']['value'] == '100'
```

还要独立测试：mock只影响相关输入与派生结果；一条更正或释放的来源不能消失；另一项目/物料/货主/单位不泄入；筛选＋第52条仍有完整输入，超过200个相关事实也不冒称齐全；页空时`source_modes=[]`。原生MES表不改变平台余额；只读查询前后iterdump一致，撤权/重启有效。

- [ ] **Step 2: RED**：`... -m pytest tests/workflow/test_material_provenance.py tests/workflow/test_native_materials.py -q --tb=short`，确认新断言因缺quantities失败。
- [ ] **Step 3: 实现只读投影并接入事务。** 需求/收货/交接每项旧标量旁附加`quantities`；requirement保留8键required/received/in_transit/qualified/rejected/reserved/shortage/confirmed_satisfied；receipt为quantity/original_quantity/qualified/accepted/rejected/uninspected；handoff为quantity/received_quantity；带数值的卡点另附`quantity_fact`。同一页面先收集返回对象的所有quantities（包括卡点和已返回工单的quantity/trial_quantity），再调用Task1的source_modes。`MaterialControlPage.source_modes_scope='returned_quantities'`。概览旧来源汇总单独标`source_modes_scope='project_source_records'`，以同一来源解析规则覆盖全项目，不保留501条任意截断；不冒称为逐项数量汇总。
- [ ] **Step 4: GREEN**：执行新测试＋`test_quantity_provenance.py`、`test_material_control.py`、`test_material_analysis.py`、`test_supply.py`、`test_exchanges.py`、`test_material_handoffs.py`、`test_material_tasks.py`、`test_expedite_fulfillment.py`、`test_material_resolution_journey.py`；维持原结束依据和数量。记录测试命令、结果、读取范围与无源调用。
- [ ] **Step 5: Commit**：仅本任务生产/测试文件；报告fixture接口、查询复杂度和未核实历史身份的行为。

### Task 3: 既有料况页面逐项显示来源与依据

**Files:** Create `webui/src/workflow/materialControl/QuantityValue.tsx`、`QuantityValue.test.tsx`；Modify `types.ts`、`MaterialControlWorkspace.tsx`、`MaterialFlowPanel.tsx`、`MesOrderMaterials.tsx`；Modify现有`materialControl.test.tsx`/`materialControlContext.test.tsx`和MES测试；构建产物仅由现有build生成。

**Consumes:** Task2的`quantities`和`source_modes_scope`；TS类型与Python JSON字段逐字对应，旧服务没有quantities时保留原数值并显示“来源待核对”，不可默认生产/确认。

**Produces:**

```typescript
export function QuantityValue({quantity, value, unit, title}: {
  quantity?: ProvenancedQuantity; value: string | null | undefined;
  unit: string; title: string;
}): React.ReactNode;
```

- [ ] **Step 1: 先写页面失败测试。** 使用实际组件：模拟输入即使role=confirmed仍显示“模拟”；manual/native/unknown、混合环境、null数量、缺时间和旧API分别有行为。展开“数量依据”能看输入数量/单位、来源、环境、对象/版本及发生/读取时间；事实更新时间不取页面刷新时间。
- [ ] **Step 2: RED**：`npm test -- src/workflow/materialControl/QuantityValue.test.tsx`。
- [ ] **Step 3: 实现并接入。** 常规数字旁只显示简短来源和时间，完整输入按需展开。主表6个数量、详情到货/在途/拒收、流转各数量、卡点quantity_fact和独立MES组件数量均用同一组件，不把原生观察合入余额。页级来源说明明确“本页返回数量”，概览保持项目范围；完整覆盖限定平台持久记录，不将未知外部覆盖写成全量。无新增导航、无必经技术步骤、无业务写入。
- [ ] **Step 4: GREEN**：定向测试＋实际WorkflowApp项目/API/用户切换、旧响应、已有草稿及分页回退相关测试。最后执行`npm test -- --exclude src/workflow/acceptanceNavigationHttp.test.tsx`及`npm run test:bundle`。专用HTTP场景E30以现有宿主单独运行，确认新增只读字段不破坏实际路由/旧流程。
- [ ] **Step 5: Commit**：页面、测试及生成产物；报告可见标识、兼容回退与完整命令结果。

## 最终审查与交付

- [ ] 各Task独立完成spec＋quality审查，修复Important/Critical；整分支由独立审查者复核。
- [ ] 单独记录source_modes同源派生验收及51+分页/跨项目样本；不将M6待办截断问题标成已修复。
- [ ] 更新T2任务书与验证记录：本轮完成数量来源契约和页面呈现；M2/M1/M3/M6/M5剩余范围保留。
- [ ] 原目录变动前核对预映像、新增路径冲突和用户文件；本地快进后验证来源/旅程相关测试及产物一致。保留隔离工作树，不推送/部署，不触碰生产源。
