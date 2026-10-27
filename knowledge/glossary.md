# 制造信息化术语表

整理日期：2026-10-27。表内为学习用的简释和辨析，不替代合同、标准或具体产品的数据字典。相同缩写可能在不同企业有其他含义，正式调研时应记录本公司的定义。基础与计划术语结合[制造基础](01-foundations/01-manufacturing-process.md)及其一手来源理解，系统术语结合[系统全景](02-systems/01-system-landscape.md)理解。

## 业务模式与组织

| 术语 | 常用含义 | 接手工作时注意什么 |
| --- | --- | --- |
| 离散制造 | 以可区分零件、组件和产品为对象的加工装配 | 常需关注结构、工序、单件或批次关系 |
| 流程制造 | 以配方、工艺条件和物料转化为特征的生产 | 可能涉及连续过程、批量、效期和联副产品 |
| MTS | Make to Stock，按库存或预测组织生产 | 预测与库存策略影响积压和服务水平 |
| MTO | Make to Order，按订单组织生产 | 订单进入后仍可能依赖通用物料备货 |
| ATO | Assemble to Order，按订单装配 | 关注通用组件、配置规则与装配能力 |
| ETO | Engineer to Order，按订单开展工程设计 | 工程交付与变更会影响采购和生产计划 |
| OEM | 原始设备制造商，或特定合作中的生产关系称呼 | 商务语境不同，须说清设计与制造责任 |
| ODM | 原始设计制造商 | 不能仅凭称呼判断知识产权与质量责任 |
| EMS | Electronics Manufacturing Services，电子制造服务 | 关注客户提供资料、物料和制造责任边界 |
| NPI | New Product Introduction，新产品导入 | 连接工程、工艺、供应与量产准备 |
| EVT | Engineering Validation Test，工程验证阶段称呼 | 阶段名称与退出标准依企业而异 |
| DVT | Design Validation Test，设计验证阶段称呼 | 不因完成测试就自动允许量产 |
| PVT | Production Validation Test，生产验证阶段称呼 | 应理解实际制造条件与放行标准 |
| MP | Mass Production，量产 | 量产批准后仍需持续变更与质量控制 |
| PMC | Production and Material Control，生产与物料控制 | 实际部门职责与岗位分工需现场确认 |
| PE | 常用于 Process Engineer 或 Product Engineer | 必须确认是工艺还是产品工程等含义 |
| ME | Manufacturing Engineer，制造工程师等 | 与 PE 的职责划分依企业而异 |
| SQE | Supplier Quality Engineer，供应商质量工程师 | 关注供应质量与异常闭环责任 |
| EOL | End of Life，生命周期终止 | 要区分产品停产、物料停供与服务期 |

## 计划 物料与采购

| 术语 | 常用含义 | 接手工作时注意什么 |
| --- | --- | --- |
| S&OP | Sales and Operations Planning，销售与运营计划 | 协调需求、供应与经营目标，通常比工单层更聚合 |
| IBP | Integrated Business Planning，集成业务计划 | 具体管理范围和产品功能需按语境确认 |
| MPS | Master Production Schedule，主生产计划 | 不是所有层级物料都直接用同一主计划 |
| MRP | Material Requirements Planning，物料需求计划 | 解决物料与日期计算，不自动保证资源可执行 |
| MRP II | Manufacturing Resource Planning，制造资源计划 | 概念范围比 MRP 更广，不等于任意软件品牌 |
| RCCP | Rough-Cut Capacity Planning，粗能力计划 | 对关键资源作较聚合的能力检查 |
| CRP | Capacity Requirements Planning，能力需求计划 | 要看具体模型是否有限能力与怎样处理约束 |
| APS | Advanced Planning and Scheduling，高级计划与排程 | 求解能力取决于资源、规则和数据建模 |
| ATP | Available to Promise，可承诺量 | 需要明确供应、需求和时点范围 |
| CTP | Capable to Promise，考虑能力的可承诺 | 应确认产品实际纳入哪些资源与约束 |
| 计划时界 | 对计划变动或处理规则作时间区分的边界 | 具体类型与含义以产品配置为准 |
| 冻结计划 | 对已承诺或临近执行计划限制变更 | 必须明确谁可突破及后果如何处理 |
| 毛需求 | 扣减可用库存和供应前的需求 | 需要说明需求来源与汇总层级 |
| 净需求 | 在约定规则下扣减供应后仍需补足的量 | 不等于简单把总需求减总库存 |
| 计划订单 | 计划生成的供应建议对象 | 不一定已经批准或进入实际执行 |
| 计划接收 | 希望新增供应到达的数量和日期 | 与已存在订单的预计接收区分 |
| 计划下达 | 按提前期反推的供应启动时间和数量 | 不能把建议下达视为采购已完成 |
| 预计接收 | 已有供应在未来预计到达的量 | 必须处理部分接收、逾期、取消与质量状态 |
| 需求追溯 | 将供应或缺口关联到上层需求 | 关联精度和动态变化受系统能力影响 |
| 逐批订货 | Lot-for-Lot，按该期净需求补足 | 是教学和计划策略之一，非普遍最优 |
| MOQ | Minimum Order Quantity，最小订购量 | 与包装倍量、价格阶梯不是同一规则 |
| 安全库存 | 为需求或供应不确定性设置的缓冲 | 需要明确策略、服务目标与维护责任 |
| 提前期 | 从约定起点到约定完成点的时间 | 区分采购、加工、运输、检验和排队 |
| 采购申请 | 请求采购某对象的内部业务单据 | 与对供应商形成承诺的采购订单区分 |
| PO | Purchase Order，采购订单 | 关注批准、变更、承诺与未结数量 |
| ASN | Advanced Shipping Notice，预先发货通知 | 通知不等于实际收货和质量放行 |
| AVL | Approved Vendor List，合格或批准供应商清单 | 批准范围可能限定物料、工厂或条件 |
| 替代料 | 经规定条件批准可替换使用的物料 | 不应只按名称相似或参数接近直接替换 |

## 工程 主数据与生产

| 术语 | 常用含义 | 接手工作时注意什么 |
| --- | --- | --- |
| 主数据 | 多业务反复使用的基础业务对象数据 | 需要所有者、批准和生命周期 |
| BOM | Bill of Materials，物料清单 | 说明产品组成，用量与适用版本不能缺失 |
| EBOM | Engineering BOM，工程物料清单 | 表达设计结构，不必等于现场装配结构 |
| MBOM | Manufacturing BOM，制造物料清单 | 应适合制造组织与实际投料 |
| BOP | Bill of Process，过程或工艺结构 | 不同产品中的对象定义存在差异 |
| Routing | 工艺路线 | 连接工序顺序、资源与标准时间 |
| 工作中心 | 能力、成本或排程中使用的资源组织单元 | 不一定对应一台物理设备 |
| 工序 | 路线中的作业步骤 | 需要说明开始、完成、检验及资源条件 |
| 标准工时 | 对约定作业条件设定的时间基准 | 区分准备时间、单件时间和人工设备时间 |
| 换型 | 切换产品、工装或配置的准备活动 | 顺序相关的换型会影响排程 |
| 工单 | 指定产品、数量、时间与执行要求的生产对象 | 工单状态与真实现场进度需对应 |
| 报工 | 记录工序或工单的实际工作结果 | 完工数量、工时与质量数量口径需一致 |
| 倒冲 | 按约定触发与标准用量自动形成耗料 | 仍需处理差异与实物核对 |
| WIP | Work in Process，在制品 | 实物、数量、工序状态与核算范围要说清 |
| 委外 | 将部分加工或制造交由外部组织 | 发料、在途、产出、损耗与质量需要衔接 |
| 批次 | 按生产、采购等条件组织的一组对象 | 批次如何生成、拆并与追溯应有规则 |
| SN | Serial Number，序列号 | 对单个实例识别，不等同于产品型号 |
| UOM | Unit of Measure，计量单位 | 换算、精度与基本单位影响全链路数量 |
| ECO | Engineering Change Order，工程变更单等 | 名称和审批对象以公司流程为准 |
| ECN | Engineering Change Notice，工程变更通知等 | 与 ECO 的先后及职责不存在所有企业统一规则 |
| Effectivity | 生效条件或适用性 | 可按日期、序列号、批次等确定适用范围 |
| As-designed | 按设计的结构或配置 | 与实际制造记录可能不同 |
| As-built | 实际制造形成的结构或配置 | 返工换件后要保留历史与现状关系 |
| As-maintained | 经过维护后的实际配置 | 连接出厂、服务更换和当前状态 |
| DFM | Design for Manufacturability，可制造性设计 | 规则检查结果不能代替全部制造可行性判断 |
| SOP | Standard Operating Procedure，标准作业程序 | 在其他语境也可能指量产启动，需确认 |

## 质量 库存与运营指标

| 术语 | 常用含义 | 接手工作时注意什么 |
| --- | --- | --- |
| IQC | Incoming Quality Control，来料质量控制 | 收到货物与检验放行为不同事件 |
| IPQC | In-Process Quality Control，过程质量控制 | 应关联工序、版本和原始结果 |
| OQC | Outgoing Quality Control，出货质量控制 | 不应与所有完工检验概念混用 |
| FAI | First Article Inspection，首件检验等 | 触发条件与范围需按流程确认 |
| NCR | Nonconformance Report，不符合报告等 | 记录对象、缺陷、隔离、处置和批准 |
| MRB | Material Review Board，不合格物料评审机制等 | 不能直接理解为一座仓库或一个固定状态 |
| CAPA | Corrective and Preventive Action，纠正与预防措施 | 需有原因、措施与效果验证 |
| 8D | Eight Disciplines，结构化问题解决方法 | 完成表格不代表根因已证实 |
| APQP | Advanced Product Quality Planning，先期产品质量策划 | 汽车行业工具的具体适用需确认 |
| PPAP | Production Part Approval Process，生产件批准程序 | 按客户与行业要求使用 |
| FMEA | Failure Mode and Effects Analysis，失效模式与影响分析 | 风险排序不能替代实际控制措施 |
| Control Plan | 控制计划 | 连接特性、方法、频率与异常反应 |
| SPC | Statistical Process Control，统计过程控制 | 控制限与产品规格限不同 |
| MSA | Measurement System Analysis，测量系统分析 | 测量数据本身也需要可信度评价 |
| GR&R | Gage Repeatability and Reproducibility，量具重复性与再现性 | 是测量系统研究的一部分 |
| Cp | 常用过程能力指标 | 需符合过程与分布等适用前提 |
| Cpk | 同时反映波动与偏离规格中心影响的能力指标 | 不能只看一个值而忽略数据与过程条件 |
| AQL | Acceptance Quality Limit，接收质量限 | 不是“允许所有批次实际有这么多不良” |
| FPY | First Pass Yield，一次通过率 | 返工后通过不能计为首次通过 |
| RTY | Rolled Throughput Yield，滚动通过率 | 各工序通过率组合须有一致统计范围 |
| OEE | Overall Equipment Effectiveness，设备综合效率 | 通常组合可用率、性能与质量，须定义分母 |
| OTD | On-Time Delivery，准时交付 | 承诺日、要求日、订单行及部分交付口径须明确 |
| OTIF | On-Time In-Full，按时足量交付 | 不等同于只检查发货时间 |
| 账实准确率 | 库存记录与实物相符程度 | 按品项、库位、数量或金额会得出不同结果 |
| 库存周转 | 库存流转效率的衡量方式 | 数据周期、分子分母与平均方式需要一致 |
| 呆滞料 | 超过约定使用或周转条件的物料 | 规则与处置责任需要明确 |
| 冻结库存 | 因质量或业务原因限制使用的库存 | 冻结不必意味着物理上不存在 |
| 齐套 | 任务所需物料满足约定准备条件 | 要定义数量、时间、质量与位置范围 |
| Takt time | 根据可用时间和客户需求计算的需求节拍 | 与实际生产周期不同 |
| Cycle time | 某项作业重复或完成的周期时间 | 起止点、并行资源与产品条件要明确 |
| Lead time | 对象跨越一段业务流程的总历时 | 常包含等待，与纯加工时间不同 |
| VSM | Value Stream Mapping，价值流图 | 同时观察物料与信息流 |
| 瓶颈 | 对业务吞吐产生约束的环节 | 会随产品组合、资源状态和时间变化 |

质量方法进一步解释见[质量与测试数据](05-fieldwork/04-quality-lean-and-test-data.md)，该文引用 AIAG、NIST 和 Lean Enterprise Institute 的原始资料。各指标的计算与验收见[指标文章](03-implementation/02-metrics-and-business-acceptance.md)。

## 系统 集成与数据治理

| 术语 | 常用含义 | 接手工作时注意什么 |
| --- | --- | --- |
| ERP | Enterprise Resource Planning，企业资源计划 | 具体覆盖计划、物流、核算等范围依产品与实施而定 |
| PLM | Product Lifecycle Management，产品生命周期管理 | 关注产品定义、工程协作与变更等生命周期信息 |
| MES | Manufacturing Execution System，制造执行系统 | 连接生产任务与现场执行记录 |
| MOM | Manufacturing Operations Management，制造运营管理 | 常比单一执行功能覆盖更广，需核对产品范围 |
| WMS | Warehouse Management System，仓储管理系统 | 关注库内作业与库存位置状态 |
| SRM | Supplier Relationship Management，供应商关系管理 | 覆盖范围随产品与企业流程变化 |
| QMS | Quality Management System，质量管理体系或软件 | 讨论时分清管理体系与某软件产品 |
| EAM | Enterprise Asset Management，企业资产管理 | 关注资产维护与生命周期等活动 |
| CMMS | Computerized Maintenance Management System，计算机化维护管理系统 | 与 EAM 范围可能重叠 |
| SCADA | Supervisory Control and Data Acquisition，监控与数据采集 | 现场监视控制与企业业务管理职责不同 |
| PLC | Programmable Logic Controller，可编程逻辑控制器 | 属于控制环境，变更须考虑现场运行条件 |
| IIoT | Industrial Internet of Things，工业物联网 | 连接设备不等于业务数据模型已统一 |
| IT | Information Technology，信息技术 | 管理企业信息与应用等领域 |
| OT | Operational Technology，运营技术 | 直接涉及物理过程监视和控制等环境 |
| ISA-95 | 企业与控制系统集成相关标准体系 | 逻辑活动分层不等于固定网络部署 |
| OPC UA | OPC Unified Architecture，工业互操作架构 | 仍需要适用的信息模型、身份与配置 |
| API | Application Programming Interface，应用程序接口 | 接口存在不等于拥有调用或业务操作权限 |
| Event | 业务事件 | 区分事实发生、消息发送与接收处理时间 |
| CDC | Change Data Capture，变更数据捕获 | 捕获记录变化不必然提供完整业务语义 |
| 幂等 | 同一业务动作重复处理不产生重复效果的性质 | 需要业务标识、状态和持久化边界支持 |
| 对账 | 按约定范围核对跨系统业务记录 | 需要发现遗漏、重复和状态差异 |
| 数据血缘 | 数据从来源到加工使用的关联关系 | 应能解释字段、转换和版本 |
| 数字线程 | 跨生命周期连接相关产品与过程数据 | 不等同于把文件放在同一共享目录 |
| 数字孪生 | 与实际对象相关联的数字表示及其模型应用 | 需要明确对象、同步方式和使用目标 |
| 权威来源 | 对指定对象或字段拥有维护职责的来源 | 必须限定范围、时点和变更责任 |
| RBAC | Role-Based Access Control，基于角色的访问控制 | 角色还需映射真实业务范围与职责 |
| RAG | Retrieval-Augmented Generation，检索增强生成 | 有检索不自动保证证据适用、最新和授权 |
| Agent | 能在约束内组织步骤与调用工具完成任务的软件能力 | 解释、建议与真实业务动作应分别验收 |

## 常见混淆

物料与产品不是严格互斥分类，产品也可作为上层结构中的物料。BOM 不等于工艺，库存不等于可用库存，收货不等于质量放行，报工不等于出货。系统集成不是让所有字段都互相覆盖，实时也不是每类数据都应采用的唯一频率。对这些关系有疑问时，应回到对象、状态、时间和职责四个维度。
