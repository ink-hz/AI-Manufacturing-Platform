# MES近期工单与所属组件修复

本次在已授权真实接入范围内修复业务旅程。用户选择历史工单后组件空，并误以为下方SAP是当前MES工单。只修提示不能解决采集与旅程的共同问题，故复核源事实及职责。

## 已核实事实

生产站点1000下，该历史工单创建于2019年，原组件表精确SITE+SHOP_ORDER也为0行。对另一个已有组件的精确工单，旧queryMshoporderresb返回0，原表同站点精确所属工单返回1，不能继续用该不透明接口作为所属组件真值。

两份2020年一手接口说明定义M_SHOP_ORDER_RESB.SHOP_ORDER为组件所属工单、AUFNR为父工单；历史客户端也按t.shop_order关联工单头。原表字段SITE、SHOP_ORDER、AUFNR、RSNUM、RSPOS、MATNR、BDMNG、ENMNG、MEINS、LGORT及COUNT/ROW_NUMBER分页投影已由父代理固定只读探针核实。最近创建工单固定SELECT也已取得5条、其中4条存在所属组件。原始证据仅在根私有 `.superpowers/mes-order-components-20261116/`。

## 职责与兼容

- MES近期工单→同站点精确所属组件→该物料优先级/相关IQC仍为主旅程。不从MES生产号猜SAP测试号，不拼成齐套或线边实收。
- 原生新增 `source_orders_recent(prefix,after,actor_id,*,expected_fingerprint=None)` 和 `collect_order_materials_by_owner(shop_order,actor_id,*,expected_fingerprint=None)`；原有两个legacy方法与通用query行为保留。私有固定profile不列入通用query可调用清单。
- Mac RPC仍只有5种operation。source_orders可选择闭合可选字段`directory_mode:'recent'`，order_materials可选择`component_mode:'owner'`；省略时仍走旧方法。无其他字符串、SQL、URL、表/列、站点或模式可由调用方提供。
- 新云selector的公开source_orders/collect_order_materials转到上述新方法；relay发送精确模式字段，native直连也转新方法。原生来源fingerprint/config/token不变，允许先更新Mac、旧云继续走legacy，再部署新云。
- 工作流观察缓存使用明确v2投影键，旧观察保留但不误用旧目录/旧组件的缓存；公开scope和来源描述不变。不改schema、dataset或正式业务行。

## 固定读取

新组件profile `source_order_components`：json_body到现有customCommon只读路径；固定SQL按`SITE=:SITE AND SHOP_ORDER=:SHOP_ORDER`。内层投影上述9个业务字段、`COUNT(*) OVER() AS TOTAL_ROWS`、`ROW_NUMBER() OVER(ORDER BY RSNUM ASC,RSPOS ASC) AS READ_ROW_NUM`，外层按代码持有的页范围最多5行。每行TOTAL_ROWS与READ_ROW_NUM校验、精确十进制、所属身份、唯一键、分页总数、100行/20页完整性与来源指纹均保留。首个精确所属查询0行允许返回total0/components[]和该页request_id；不等于需求或库存为0。

近期目录profile `source_orders_recent`：同站点M_SHOP_ORDER，CREATE_DATE DESC NULLS LAST、SHOP_ORDER DESC，每页最多5行。按精确SHOP_ORDER游标在同站点头表查锚点创建时间，固定谓词推进日期/编号；prefix仍只作绑定前缀，空绑定不传NULL。可空日期排最后；缺失锚点不扩为全表重读。投影CREATE_DATE原始Timestamp及`CASE WHEN EXISTS`同站点同SHOP_ORDER组件后得HAS_COMPONENTS。原始毫秒/nanos转为可比较UTC ISO日期字符串；列表只称最近创建，不称生产中。单页无重复，日期/同日期编号顺序校验。

返回顶层仍为source/fingerprint/items/next_cursor/total(null)/page_size(5)/request_id。recent items为`{shop_order,description,created_at:string|null,has_components:boolean}`。游标仍是最后一行原始工单号。legacy items仍只有前两字段，旧格式/旧调用不变。

## 页面

默认读近期目录，显示创建日期和组件记录存在状态；仍可按前缀精确找历史工单。空组件显示“未查到该工单的MES组件记录，暂不能分析料况”，不报连接失败、不显示需求0或完整组件0。

SAP浏览器放在显式“单独查询SAP”按钮后，默认不挂载；选择MES工单不自动打开SAP或带入同号。进入后仍显示其真实测试来源。保持原MES生产/SAP测试来源、账号/工单/物料异步隔离和失败缓存策略。

## 验收边界

生产源业务写入0；必要登录及代码持有纯SELECT、限定对象/5行/原超时与审计。主业务源读取无任意SQL，原20页/100行/2MiB/65秒/4并发不放宽。

TDD和独立评审后，先本机新方法：近期两页、历史工单空、已观测反例1条、既有正例12条；再Mac新服务和云端同范围读取、零正式对象的HTTP/React旅程。保全旧缓存与SAP/产测/SDK/全部有序Compose/平台静态/其他容器/Nginx，固定37项及OEM候选后受控发布。员工浏览器仍用户验收，跨系统生产订单映射仍未证明。
