# SAP真实测试环境接入：工单到物料供需

用户已要求按当前权限开发真实SAP测试环境接入，缺权后再说明。此决定接续机器人OEM料况设计和T1/T2，以真实测试读取替代本轮SAP mock开发；历史mock设计保留为历史，不作为真实数据失败时的回退。

## 用户旅程与范围

在现有“计划与物料”入口查询一个明确的SAP生产工单及工厂，直接查看工单和完整组件，不要求先在平台登记第二份工单。由具体组件打开该物料/工厂的MRP供需。首期使用当前已验证的BAPI_PRODORD_GET_DETAIL与BAPI_MATERIAL_STOCK_REQ_LIST，凭据来自受控配置。当前生产平台的跨项目源数据浏览先限定平台配置管理员；项目成员不因拥有一个项目权限就能查询任意SAP工单。

页面持续标明“SAP测试环境”，保留系统/客户端、读取时间、源单据及数量原含义。组件需求量与已提量分别显示；MRP为物料/工厂范围，不能当作本单分配库存或直接判齐套。测试SAP与生产MES保持独立，不建立同号自动关联，不修改平台正式需求、库存、质量或预留。

## 边界与数据流

1. SAP原生层新增经过源代码核对的、精确单工单只读BAPI，固定只取抬头和组件，禁止集体工单扩展及客户端自定义标志。返回单号和工厂必须匹配输入，组件最多500条，超过则整体拒绝，禁止悄悄截断。
2. 复用已有MRP固定只读调用，保留50条完整性上限，51条整体失败并明确提示，绝不伪造分页或净需求计算。
3. 工作流增加管理员授权的固定读取路由，原生服务由宿主注入。GET只读平台已存观察；POST仅刷新源读取及保存平台本地快照，不执行SAP业务操作。既有read_only/CSRF与宿主精确路径鉴权保持有效。
4. 新增独立的本地SAP观察表，按配置指纹、查询种类与精确对象键隔离。仅保存每个键最后一个成功快照；失败不覆盖成功内容，返回错误及旧快照，由页面显示原读取时间和刷新失败。不得回落mock。配置变化后不呈现旧环境快照。
5. SAP审计仍仅保存请求标识、函数、时点、结果，不记录凭据/物料/数量原文。业务快照属于受控工作流数据库，不写入Git或公开报告。

## 对外业务契约

基础路径：`/api/v1/manufacturing/workflow/material-control/sap`。

- `GET /status`：管理员获得configured/environment/system_id/client，只返回非敏感环境身份；无配置给明确不可用状态。
- `GET|POST /production-order?number=...&plant=...`：固定工单+工厂读取。GET不触源；POST实际刷新。
- `GET|POST /stock-requirements?material=...&plant=...`：固定物料+工厂MRP；GET不触源。
- 观察响应：`{snapshot:null|{id,kind,scope,source,collected_at,data},refresh_error:null|{code,message}}`。source含system/environment/system_id/client/namespace，origin=native，fact_role=observation。data中的数量保持十进制字符串，不能转浮点。
- 工单data：`{number,plant,material,description,quantity,unit,components:[{component_key,material,plant,storage_location,required_quantity,withdrawn_quantity,unit,required_at}],total}`。
- MRP data保留已校验的`mrp_list`和`items`原字段，增加产品呈现所需明确字段映射，不推算分配/净缺料。

## 验收

隔离测试覆盖固定请求防篡改、作用域匹配、完整性上限、错误/警告、数值原样、身份与环境来源、鉴权先于I/O、配置切换、失败保留成功快照、刷新竞争、存储不可用与无mock回退。前端覆盖真实空结果、环境标签、组件进入MRP、失败旧快照标识、切换工单/物料/账号后的异步隔离。真实测试用AI03和既有真实对象，记录脱敏计数及请求关联证据。生产MES/WMS/SAP全程只读；不调用MRP执行或业务写函数。浏览器页面验收由用户进行。
